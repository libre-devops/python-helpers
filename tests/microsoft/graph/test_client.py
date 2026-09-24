from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes.http import fake_session, json_body, routes
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.microsoft.graph import GraphClient, graph_path, iso_duration

USER_ID = "88888888-8888-8888-8888-888888888888"
APP_ID = "99999999-9999-9999-9999-999999999999"
NEXT = "https://graph.microsoft.com/v1.0/users?$skiptoken=page2"


def graph(table):
    session, adapter = fake_session(routes(table))
    return GraphClient.create(StaticTokens(), TENANT, session=session), adapter


def query(request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(request.url).query).items()}


@pytest.mark.parametrize(
    ("path", "beta", "expected"),
    [
        ("users", False, "/v1.0/users"),
        ("/me/memberOf", False, "/v1.0/me/memberOf"),
        ("users", True, "/beta/users"),
        ("beta/me", False, "/beta/me"),
        ("/v1.0/devices?$top=5", False, "/v1.0/devices?$top=5"),
        ("users?$filter=displayName eq 'Ana'", False, "/v1.0/users?$filter=displayName eq 'Ana'"),
        (NEXT, False, NEXT),
    ],
)
def test_paths_are_put_the_way_graph_wants_them(path, beta, expected):
    assert graph_path(path, beta=beta) == expected


@pytest.mark.parametrize("path", ["", "   ", "users/../me", "users\\me", "users me"])
def test_unsafe_or_empty_paths_are_refused(path):
    with pytest.raises(InputError):
        graph_path(path)


def test_beta_and_an_explicit_v1_path_disagree():
    with pytest.raises(InputError, match="disagree"):
        graph_path("v1.0/users", beta=True)


def test_a_full_url_to_another_host_is_refused_before_any_request():
    client, adapter = graph({})
    with pytest.raises(ApiError, match="refusing to send a token"):
        client.get("https://evil.example.com/v1.0/users")
    assert adapter.requests == []


def test_advanced_queries_send_consistency_level():
    client, adapter = graph({"/v1.0/users": (200, {"value": []})})
    client.get("users", eventual=True)
    assert adapter.requests[0].headers["ConsistencyLevel"] == "eventual"
    client.get("users")
    assert "ConsistencyLevel" not in adapter.requests[1].headers


def pages(request):
    if "skiptoken" in request.url:
        return (200, {"value": [{"id": "3"}]})
    return (200, {"value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": NEXT, "@odata.count": 3})


def test_one_page_by_default_every_page_with_all_and_a_limit_stops_early():
    client, adapter = graph({"/v1.0/users": pages})
    first = client.page("users")
    assert ([item["id"] for item in first.items], first.more, first.count) == (["1", "2"], True, 3)
    every = client.page("users", all_pages=True, eventual=True)
    assert [item["id"] for item in every.items] == ["1", "2", "3"]
    assert not every.more
    assert adapter.requests[-1].headers["ConsistencyLevel"] == "eventual"  # on the next page too
    limited = client.page("users", limit=1)
    assert ([item["id"] for item in limited.items], limited.more) == (["1"], True)
    three = client.page("users", limit=3)
    assert [item["id"] for item in three.items] == ["1", "2", "3"]


def test_a_single_object_is_not_a_collection():
    client, _ = graph({"/v1.0/me": (200, {"id": USER_ID})})
    with pytest.raises(InputError, match="single object"):
        client.page("me")


def test_a_user_is_found_by_upn_id_or_name():
    client, adapter = graph(
        {
            "/v1.0/users/ana@example.com": (
                200,
                {"id": USER_ID, "userPrincipalName": "ana@example.com"},
            ),
            f"/v1.0/users/{USER_ID}": (200, {"id": USER_ID}),
            "/v1.0/users": (200, {"value": [{"id": USER_ID, "displayName": "Ana"}]}),
        }
    )
    assert client.lookup("user", "ana@example.com")[0]["id"] == USER_ID
    assert client.lookup("user", USER_ID, select="id")[0]["id"] == USER_ID
    assert query(adapter.requests[1])["$select"] == "id"
    assert client.lookup("user", "Ana")[0]["displayName"] == "Ana"
    assert query(adapter.requests[2])["$filter"] == (
        "userPrincipalName eq 'Ana' or displayName eq 'Ana' or mail eq 'Ana'"
    )


def test_a_device_falls_back_to_its_short_name():
    def devices(request):
        name = query(request)["$filter"].split("'")[1]
        return (200, {"value": [{"id": "d1", "displayName": name}] if name == "web01" else []})

    client, adapter = graph({"/v1.0/devices": devices})
    assert client.lookup("device", "web01.corp.example.com")[0]["displayName"] == "web01"
    assert len(adapter.requests) == 2


def test_an_app_id_is_tried_when_the_object_id_is_not_found():
    client, adapter = graph(
        {
            f"/v1.0/applications/{APP_ID}": (404, {"error": {"code": "Request_ResourceNotFound"}}),
            "/v1.0/applications": (200, {"value": [{"id": "o1", "appId": APP_ID}]}),
        }
    )
    assert client.lookup("app", APP_ID)[0]["id"] == "o1"
    assert query(adapter.requests[1])["$filter"] == f"appId eq '{APP_ID}'"


def test_a_group_id_that_is_not_found_is_nothing_and_errors_still_raise():
    client, _ = graph({f"/v1.0/groups/{USER_ID}": (404, {"error": {"code": "NotFound"}})})
    assert client.lookup("group", USER_ID) == []
    denied, _ = graph({"/v1.0/users/ana@example.com": (403, {"error": {"code": "Forbidden"}})})
    with pytest.raises(ApiError):
        denied.lookup("user", "ana@example.com")
    with pytest.raises(InputError, match="unknown kind"):
        denied.lookup("printer", "x")
    with pytest.raises(InputError, match="no user named"):
        denied.lookup("user", "  ")


def test_a_upn_that_is_not_found_is_searched_by_name():
    client, _ = graph(
        {
            "/v1.0/users/bob@example.com": (404, {"error": {"code": "Request_ResourceNotFound"}}),
            "/v1.0/users": (200, {"value": []}),
        }
    )
    assert client.lookup("user", "bob@example.com") == []


def test_me_and_the_service_principal_behind_an_app_token():
    client, _ = graph(
        {
            "/v1.0/me": (200, {"id": USER_ID, "displayName": "Ana"}),
            "/v1.0/servicePrincipals": (200, {"value": [{"id": "sp1", "appId": APP_ID}]}),
        }
    )
    assert client.me()["displayName"] == "Ana"
    assert client.service_principal(APP_ID)["id"] == "sp1"
    assert client.service_principal("not-a-guid") is None


def test_hunting_posts_the_query_and_keeps_the_column_order():
    reply = {
        "schema": [
            {"name": "Timestamp", "type": "DateTime"},
            {"name": "SenderFromAddress", "type": "String"},
        ],
        "results": [{"SenderFromAddress": "x@example.com", "Timestamp": "2026-09-24T09:00:00Z"}],
    }
    client, adapter = graph({"/v1.0/security/runHuntingQuery": (200, reply)})
    result = client.hunt("EmailEvents | take 1", timespan=timedelta(days=7))
    assert result.columns == ("Timestamp", "SenderFromAddress")
    assert json_body(adapter.requests[0]) == {"Query": "EmailEvents | take 1", "Timespan": "P7D"}
    client.hunt("EmailEvents")
    assert "Timespan" not in json_body(adapter.requests[1])


def test_hunting_explains_a_missing_scope_and_refuses_an_empty_query():
    client, _ = graph({"/v1.0/security/runHuntingQuery": (403, {"error": {"code": "Forbidden"}})})
    with pytest.raises(ApiError) as caught:
        client.hunt("DeviceInfo")
    assert "ThreatHunting.Read.All" in (caught.value.hint or "")
    with pytest.raises(InputError, match="empty"):
        client.hunt("  ")


def test_a_hunt_without_a_schema_takes_its_columns_from_the_rows():
    client, _ = graph({"/v1.0/security/runHuntingQuery": (200, {"results": [{"a": 1}]})})
    assert client.hunt("x").columns == ("a",)


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        (timedelta(days=7), "P7D"),
        (timedelta(hours=6), "PT6H"),
        (timedelta(minutes=90), "PT90M"),
        (timedelta(seconds=45), "PT45S"),
    ],
)
def test_iso_durations(span, expected):
    assert iso_duration(span) == expected


def test_a_timespan_must_be_positive():
    with pytest.raises(InputError, match="positive"):
        iso_duration(timedelta())


def test_a_suspended_service_keeps_its_own_hint():
    suspended = (403, {"error": {"code": "Unauthorized", "message": "MTP status: Suspended"}})
    client, _ = graph({"/v1.0/security/runHuntingQuery": suspended})
    with pytest.raises(ApiError) as caught:
        client.hunt("DeviceInfo")
    assert "suspended in this tenant" in (caught.value.hint or "")
