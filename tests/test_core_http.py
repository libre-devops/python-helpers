import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from fakes import fake_session, json_body
from libre_devops_helpers.core.errors import ApiError
from libre_devops_helpers.core.http import ApiClient, retry_after_seconds

BASE = "https://graph.microsoft.com"


def client(handler, **options):
    session, adapter = fake_session(handler)
    sleeps: list[float] = []
    api = ApiClient(BASE, lambda: "tok", session=session, sleep=sleeps.append, **options)
    return api, adapter, sleeps


def test_get_sends_bearer_token_and_encoded_query():
    api, adapter, _ = client(lambda request: (200, {"ok": True}))
    assert api.get("/v1.0/devices", params={"$filter": "displayName eq 'web 01'"}) == {"ok": True}
    request = adapter.requests[0]
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["User-Agent"].startswith("ldo/")
    query = parse_qs(urlsplit(request.url).query)
    assert query == {"$filter": ["displayName eq 'web 01'"]}
    assert "%20" in request.url


def test_retries_on_429_honouring_retry_after():
    replies = iter([(429, {}, {"Retry-After": "7"}), (200, {"ok": True})])
    api, adapter, sleeps = client(lambda request: next(replies))
    assert api.get("/x") == {"ok": True}
    assert sleeps == [7.0]
    assert len(adapter.requests) == 2


def test_gives_up_after_max_attempts_on_5xx():
    api, adapter, sleeps = client(lambda request: (503, {}), max_attempts=3)
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 503
    assert len(adapter.requests) == 3
    assert len(sleeps) == 2


def test_403_is_not_retried_and_carries_the_api_error_details():
    body = {"error": {"code": "Authorization_RequestDenied", "message": "Insufficient privileges"}}
    api, adapter, _ = client(lambda request: (403, body, {"request-id": "abc-123"}))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    error = caught.value
    assert (error.status, error.code, error.request_id) == (
        403,
        "Authorization_RequestDenied",
        "abc-123",
    )
    assert "Insufficient privileges" in str(error)
    assert error.hint
    assert "role or permission" in error.hint
    assert len(adapter.requests) == 1


def test_a_403_from_a_suspended_service_says_so():
    # Defender for Endpoint's reply when the tenant's licence or trial has ended.
    body = {
        "error": {"code": "Unauthorized", "message": "reason of failure: Suspended account mode"}
    }
    api, _, _ = client(lambda request: (403, body))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert "suspended" in (caught.value.hint or "")


def test_connection_errors_are_retried_then_reported():
    api, adapter, _ = client(lambda request: requests.ConnectionError("down"), max_attempts=2)
    with pytest.raises(ApiError, match="after 2 attempts"):
        api.get("/x")
    assert len(adapter.requests) == 2


def test_redirects_are_not_followed():
    api, adapter, _ = client(lambda request: (302, {}, {"Location": "https://elsewhere.test/"}))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 302
    assert len(adapter.requests) == 1


def test_get_all_follows_next_links():
    def handler(request):
        if "page=2" in request.url:
            return (200, {"value": [{"id": "b"}]})
        return (200, {"value": [{"id": "a"}], "@odata.nextLink": f"{BASE}/v1.0/devices?page=2"})

    api, _, _ = client(handler)
    assert [item["id"] for item in api.get_all("/v1.0/devices")] == ["a", "b"]


def test_a_next_link_to_another_host_is_refused():
    api, adapter, _ = client(
        lambda request: (200, {"value": [], "@odata.nextLink": "https://evil.test/steal"})
    )
    with pytest.raises(ApiError, match="refusing to send a token"):
        list(api.get_all("/v1.0/devices"))
    assert len(adapter.requests) == 1


def test_base_url_must_be_https():
    with pytest.raises(ValueError, match="https"):
        ApiClient("http://graph.microsoft.com", lambda: "tok")


def test_retry_after_accepts_an_http_date():
    response = requests.Response()
    later = datetime.now(UTC) + timedelta(seconds=30)
    response.headers["Retry-After"] = format_datetime(later, usegmt=True)
    seconds = retry_after_seconds(response)
    assert seconds is not None
    assert 25 <= seconds <= 30


def test_post_sends_json_and_is_retried_like_a_get():
    replies = iter([(503, {}), (200, {"rows": 1})])
    api, adapter, sleeps = client(lambda request: next(replies))
    assert api.post("/query", {"Query": "x"}) == {"rows": 1}
    assert [json_body(request) for request in adapter.requests] == [{"Query": "x"}] * 2
    assert adapter.requests[0].headers["Content-Type"] == "application/json"
    assert len(sleeps) == 1


def test_get_all_follows_arm_style_next_links():
    def handler(request):
        if "page=2" in request.url:
            return (200, {"value": [{"id": "b"}]})
        return (200, {"value": [{"id": "a"}], "nextLink": f"{BASE}/subscriptions?page=2"})

    api, _, _ = client(handler)
    items = api.get_all("/subscriptions", next_link="nextLink")
    assert [item["id"] for item in items] == ["a", "b"]


def test_a_tokenless_client_may_use_http_only_on_a_local_address():
    assert ApiClient("http://169.254.169.254/x", None, allow_http=True).base_url
    assert ApiClient("http://127.0.0.1:41000/msi", None, allow_http=True).base_url
    with pytest.raises(ValueError, match="https"):
        ApiClient("http://login.example.test", None, allow_http=True)
    with pytest.raises(ValueError, match="https"):
        ApiClient("http://169.254.169.254/x", lambda: "tok", allow_http=True)


def test_a_tokenless_client_sends_no_authorization_header():
    session, adapter = fake_session(lambda request: (200, {}))
    ApiClient(BASE, None, session=session).get("/x")
    assert "Authorization" not in adapter.requests[0].headers


def test_an_oauth_error_body_is_read():
    body = {"error": "invalid_client", "error_description": "AADSTS700016: App not found.\nx"}
    api, _, _ = client(lambda request: (400, body))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert caught.value.code == "invalid_client"
    assert str(caught.value).endswith("invalid_client: AADSTS700016: App not found.")


def test_json_inside_a_graph_error_message_is_unwrapped():
    # Graph's shape when a PIM call lacks its scope.
    inner = '{"errorCode":"PermissionScopeNotGranted","message":"missing scope RoleX"}'
    body = {"error": {"code": "UnknownError", "message": inner}}
    api, _, _ = client(lambda request: (403, body))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert str(caught.value) == (
        "API: HTTP 403 UnknownError: PermissionScopeNotGranted: missing scope RoleX"
    )
    assert "lacks the permission" in (caught.value.hint or "")


def test_intunes_doubly_nested_401_is_unwrapped_and_hinted_as_a_permission_problem():
    innermost = (
        '{\r\n  "_version": 3,\r\n  "Message": "An error has occurred - Operation ID: 0"\r\n}'
    )
    middle = json.dumps({"ErrorCode": "Forbidden", "Message": innermost})
    api, _, _ = client(
        lambda request: (401, {"error": {"code": "UnknownError", "message": middle}})
    )
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert str(caught.value) == (
        "API: HTTP 401 UnknownError: Forbidden: An error has occurred - Operation ID: 0"
    )
    assert "lacks the permission" in (caught.value.hint or "")


def test_a_firewall_block_is_flattened_to_one_line_and_hinted():
    # Key Vault's reply when its network rules do not allow the caller's address.
    message = (
        "Client address is not authorized and caller is not a trusted service.\n"
        "Client address: 203.0.113.9\n"
        "Vault: kv-app"
    )
    api, _, _ = client(lambda request: (403, {"error": {"code": "Forbidden", "message": message}}))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert "\n" not in str(caught.value)
    assert "Client address: 203.0.113.9 Vault: kv-app" in str(caught.value)
    assert "firewall" in (caught.value.hint or "")


def test_a_very_long_message_is_capped():
    api, _, _ = client(lambda request: (400, {"error": {"code": "Bad", "message": "x" * 5000}}))
    with pytest.raises(ApiError) as caught:
        api.get("/x")
    assert len(str(caught.value)) < 500
    assert str(caught.value).endswith("...")
