import json
import re

from fakes.http import routes
from fakes.ids import CLIENT_ID, TENANT
from fakes.tenant import run
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.core.errors import AmbiguousError, NotFoundError

USER_ID = "88888888-8888-8888-8888-888888888888"
ME = (200, {"id": USER_ID, "displayName": "Ana Analyst", "jobTitle": "SOC analyst"})
NEXT = "https://graph.microsoft.com/v1.0/users?$skiptoken=2"


def test_whoami_for_a_person_shows_who_and_the_delegated_scopes(config_file):
    result = run(config_file, routes({"/v1.0/me": ME}), ["graph", "whoami"])
    assert result.exit_code == 0, result.output
    assert re.search(r"^Signed in as\s+analyst@example.com$", result.stdout, re.MULTILINE)
    assert "Ana Analyst" in result.stdout
    assert "SOC analyst" in result.stdout
    assert "Device.Read.All, GroupMember.Read.All" in result.stdout
    record = json.loads(
        run(config_file, routes({"/v1.0/me": ME}), ["graph", "whoami", "-o", "json"]).stdout
    )
    assert (record["kind"], record["object"]["id"]) == ("user", USER_ID)


def test_whoami_for_an_app_shows_its_service_principal_and_roles(config_file):
    claims = graph_claims(appid=CLIENT_ID, roles=["Device.Read.All"], idtyp="app")
    for claim in ("upn", "scp"):
        claims.pop(claim)
    handler = routes(
        {
            f"/{TENANT}/oauth2/v2.0/token": (
                200,
                {"access_token": make_jwt(claims), "expires_in": 3600},
            ),
            "/v1.0/servicePrincipals": (200, {"value": [{"id": "sp1", "displayName": "ldo-ci"}]}),
        }
    )
    args = ["graph", "whoami", "-p", "app"]
    result = run(config_file, handler, args, environ={"AZURE_CLIENT_SECRET": "s"})
    assert result.exit_code == 0, result.output
    assert "app (application)" in result.stdout
    assert "ldo-ci" in result.stdout
    assert re.search(r"^Roles\s+Device\.Read\.All$", result.stdout, re.MULTILINE)


def test_whoami_still_answers_when_the_object_cannot_be_read(config_file):
    denied = routes({"/v1.0/me": (403, {"error": {"code": "Forbidden"}})})
    result = run(config_file, denied, ["graph", "whoami"])
    assert result.exit_code == 0, result.output
    assert "could not read the user" in result.stderr


def test_token_is_the_entra_token_for_graph(config_file):
    result = run(config_file, routes({}), ["graph", "token", "--raw"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(".") == 2  # a JWT


def users(request):
    if "skiptoken" in request.url:
        return (200, {"value": [{"id": "3", "displayName": "Cy"}]})
    body = {
        "value": [
            {
                "id": "1",
                "displayName": "Ana",
                "userPrincipalName": "ana@example.com",
                "jobTitle": "x",
            },
            {
                "id": "2",
                "displayName": "Bo",
                "userPrincipalName": "bo@example.com",
                "jobTitle": "y",
            },
        ],
        "@odata.nextLink": NEXT,
    }
    if "count" in request.url:
        body["@odata.count"] = 3
    return (200, body)


def test_get_a_collection_shows_one_page_and_says_when_there_is_more(config_file):
    result = run(config_file, routes({"/v1.0/users": users}), ["graph", "get", "users"])
    assert result.exit_code == 0, result.output
    header = result.stdout.splitlines()[0]
    assert "USERPRINCIPALNAME" in header
    assert "JOBTITLE" not in header  # the table keeps to the familiar columns
    assert "2 item(s); more exist" in result.stderr


def test_get_with_all_select_and_count_as_csv(config_file):
    args = ["graph", "get", "users", "--all", "--count", "--select", "id,jobTitle", "-o", "csv"]
    result = run(config_file, routes({"/v1.0/users": users}), args)
    assert result.stdout.splitlines() == ["ID,JOBTITLE", "1,x", "2,y", "3,"]
    assert "3 item(s) of 3" in result.stderr


def test_get_a_single_object_shows_its_fields(config_file):
    result = run(config_file, routes({"/v1.0/me": ME}), ["graph", "get", "me"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0].startswith("id ")
    as_json = run(config_file, routes({"/v1.0/me": ME}), ["graph", "get", "/me", "-o", "json"])
    assert json.loads(as_json.stdout)["displayName"] == "Ana Analyst"


def test_get_passes_query_options_and_quotes_search(config_file):
    seen = []

    def capture(request):
        seen.append(request)
        return (200, {"value": []})

    args = [
        "graph",
        "get",
        "users",
        "--filter",
        "accountEnabled eq true",
        "--search",
        "displayName:ana",
        "--orderby",
        "displayName",
        "--expand",
        "manager",
        "--top",
        "5",
        "--beta",
    ]
    result = run(config_file, routes({"/beta/users": capture}), args)
    assert result.exit_code == 0, result.output
    request = seen[0]
    assert request.headers["ConsistencyLevel"] == "eventual"
    assert "%24search=%22displayName%3Aana%22" in request.url
    assert "%24top=5" in request.url


def test_lookups_show_one_object_or_explain(config_file):
    user = (200, {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"})
    result = run(
        config_file,
        routes({"/v1.0/users/ana@example.com": user}),
        ["graph", "get-user", "ana@example.com"],
    )
    assert result.exit_code == 0, result.output
    assert "ana@example.com" in result.stdout
    two = (
        200,
        {"value": [{"id": "g1", "displayName": "Pilot"}, {"id": "g2", "displayName": "Pilot"}]},
    )
    ambiguous = run(config_file, routes({"/v1.0/groups": two}), ["graph", "get-group", "Pilot"])
    assert isinstance(ambiguous.exception, AmbiguousError)
    assert "g1, g2" in (ambiguous.exception.hint or "")
    none = run(
        config_file,
        routes({"/v1.0/applications": (200, {"value": []})}),
        ["graph", "get-app", "ghost"],
    )
    assert isinstance(none.exception, NotFoundError)


def test_several_devices_with_one_name_are_all_shown(config_file):
    stale = (
        200,
        {"value": [{"id": "d1", "displayName": "web01"}, {"id": "d2", "displayName": "web01"}]},
    )
    result = run(
        config_file, routes({"/v1.0/devices": stale}), ["graph", "get-device", "web01", "-o", "csv"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["ID,DISPLAYNAME", "d1,web01", "d2,web01"]
    assert "2 devices are named 'web01'" in result.stderr


def test_graph_hunt_runs_over_the_whole_schema(config_file):
    reply = {"schema": [{"name": "AccountUpn"}], "results": [{"AccountUpn": "ana@example.com"}]}
    handler = routes({"/v1.0/security/runHuntingQuery": (200, reply)})
    result = run(
        config_file, handler, ["graph", "hunt", "IdentityLogonEvents | take 1", "-o", "csv"]
    )
    assert result.stdout.splitlines() == ["AccountUpn", "ana@example.com"]
    assert "1 row(s)" in result.stderr
