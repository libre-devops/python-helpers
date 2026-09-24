from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes.http import fake_session, form_body
from fakes.ids import CLIENT_ID, TENANT
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.microsoft.auth import (
    ClientSecretCredential,
    WorkloadIdentityCredential,
    federated_token_file,
    github_actions_assertion,
)
from libre_devops_helpers.microsoft.auth.entra import parse_token_response
from libre_devops_helpers.microsoft.clouds import USGOV

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

GRAPH = "https://graph.microsoft.com"


def token_endpoint(requests_seen: list, reply=None):
    def handler(request):
        requests_seen.append(request)
        return reply or (200, {"access_token": "app-token", "expires_in": 3599})

    return fake_session(handler)[0]


def test_client_secret_posts_a_client_credentials_grant_for_the_default_scope():
    seen: list = []
    credential = ClientSecretCredential(
        CLIENT_ID, "s3cret", session=token_endpoint(seen), clock=lambda: NOW
    )
    token = credential.get_token("https://management.azure.com/", TENANT)
    assert token.token == "app-token"
    assert token.expires_on == NOW + timedelta(seconds=3599)
    request = seen[0]
    assert request.url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    assert "Authorization" not in request.headers
    assert form_body(request) == {
        "client_id": CLIENT_ID,
        "client_secret": "s3cret",
        "grant_type": "client_credentials",
        "scope": "https://management.azure.com/.default",
    }


def test_the_secret_never_appears_in_repr():
    credential = ClientSecretCredential(CLIENT_ID, "s3cret", session=token_endpoint([]))
    assert "s3cret" not in repr(credential)


def test_a_rejected_secret_says_which_setting_to_check():
    reply = (
        401,
        {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided.\r\nTrace ID: x",
        },
    )
    credential = ClientSecretCredential(CLIENT_ID, "bad", session=token_endpoint([], reply))
    with pytest.raises(AuthError, match="AADSTS7000215") as caught:
        credential.get_token(GRAPH, TENANT)
    assert "Trace ID" not in str(caught.value)
    assert "AZURE_CLIENT_SECRET" in (caught.value.hint or "")


def test_workload_identity_sends_a_fresh_assertion_each_time():
    seen: list = []
    assertions = iter(["jwt-1", "jwt-2"])
    credential = WorkloadIdentityCredential(
        CLIENT_ID, lambda: next(assertions), session=token_endpoint(seen)
    )
    credential.get_token(GRAPH, TENANT)
    credential.get_token(GRAPH, TENANT)
    forms = [form_body(request) for request in seen]
    assert [form["client_assertion"] for form in forms] == ["jwt-1", "jwt-2"]
    assert forms[0]["client_assertion_type"].endswith("jwt-bearer")
    assert "client_secret" not in forms[0]


def test_a_sovereign_cloud_uses_its_own_login_host():
    seen: list = []
    credential = ClientSecretCredential(
        CLIENT_ID, "s", login_url=USGOV.login_url, session=token_endpoint(seen)
    )
    credential.get_token(USGOV.graph_url, TENANT)
    assert urlsplit(seen[0].url).netloc == "login.microsoftonline.us"


def test_the_federated_token_file_is_reread(tmp_path):
    path = tmp_path / "token"
    read = federated_token_file(path)
    path.write_text("first\n")
    assert read() == "first"
    path.write_text("second")
    assert read() == "second"
    path.write_text("")
    with pytest.raises(AuthError, match="empty"):
        read()


def test_github_actions_assertion_asks_for_the_exchange_audience():
    seen: list = []

    def handler(request):
        seen.append(request)
        return (200, {"value": "gh-oidc-jwt"})

    session, _ = fake_session(handler)
    url = "https://pipelines.actions.githubusercontent.com/abc/idtoken?api-version=2.0"
    fetch = github_actions_assertion(url, "runner-token", session=session)
    assert fetch() == "gh-oidc-jwt"
    request = seen[0]
    assert request.headers["Authorization"] == "Bearer runner-token"
    query = parse_qs(urlsplit(request.url).query)
    assert query == {"api-version": ["2.0"], "audience": ["api://AzureADTokenExchange"]}


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"expires_in": 3600}, "has no access_token"),
        ({"access_token": "t"}, "has no expiry"),
        ({"access_token": "t", "expires_in": True}, "has no expiry"),
    ],
)
def test_a_token_response_without_a_token_or_expiry_is_refused(reply, message):
    with pytest.raises(AuthError, match=message):
        parse_token_response(reply, GRAPH, TENANT, now=NOW, name="test")


def test_expiry_may_come_as_expires_on_or_a_numeric_string():
    token = parse_token_response(
        {"access_token": "t", "expires_on": str(int(NOW.timestamp()) + 60)},
        GRAPH,
        TENANT,
        now=NOW,
        name="test",
    )
    assert token.expires_on == NOW + timedelta(seconds=60)
    token = parse_token_response(
        {"access_token": "t", "expires_in": "90"}, GRAPH, TENANT, now=NOW, name="test"
    )
    assert token.expires_on == NOW + timedelta(seconds=90)


def test_an_empty_secret_is_refused_up_front():
    with pytest.raises(AuthError, match="empty"):
        ClientSecretCredential(CLIENT_ID, "")


@pytest.mark.parametrize(
    ("code", "hint"),
    [
        ("AADSTS700016", "no app with this client_id"),
        ("AADSTS70021", "no federated credential"),
        ("AADSTS90002", "no such tenant"),
        ("AADSTS50000", "check the profile's client_id and tenant_id"),
    ],
)
def test_token_endpoint_errors_come_with_a_hint(code, hint):
    reply = (400, {"error": "invalid_client", "error_description": f"{code}: nope"})
    credential = ClientSecretCredential(CLIENT_ID, "s", session=token_endpoint([], reply))
    with pytest.raises(AuthError) as caught:
        credential.get_token(GRAPH, TENANT)
    assert hint in (caught.value.hint or "")


def test_workload_identity_repr_names_only_the_client():
    credential = WorkloadIdentityCredential(CLIENT_ID, lambda: "secret-assertion")
    assert "secret-assertion" not in repr(credential)
    assert CLIENT_ID in repr(credential)


def test_a_missing_or_empty_federated_token_file_is_an_error(tmp_path):
    with pytest.raises(AuthError, match="cannot read"):
        federated_token_file(tmp_path / "missing")()
    empty = tmp_path / "token"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(AuthError, match="is empty"):
        federated_token_file(empty)()


def test_github_actions_assertion_explains_a_missing_permission_or_value():
    url = "https://pipelines.actions.githubusercontent.com/abc/idtoken"
    denied, _ = fake_session(lambda request: (403, {"message": "forbidden"}))
    with pytest.raises(AuthError) as caught:
        github_actions_assertion(url, "runner-token", session=denied)()
    assert "id-token: write" in (caught.value.hint or "")
    blank, _ = fake_session(lambda request: (200, {"value": ""}))
    with pytest.raises(AuthError, match="no token value"):
        github_actions_assertion(url, "runner-token", session=blank)()
