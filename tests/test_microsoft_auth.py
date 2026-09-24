from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes import TENANT, az_runner, fake_session, form_body
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.microsoft.auth import (
    AzureCliCredential,
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
    credential_for,
    federated_token_file,
    github_actions_assertion,
)
from libre_devops_helpers.microsoft.clouds import USGOV
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.process import AzCliError

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
CLIENT_ID = "77777777-7777-7777-7777-777777777777"
GRAPH = "https://graph.microsoft.com"


# Azure CLI -----------------------------------------------------------------------


def test_azure_cli_passes_resource_and_tenant_and_parses_expiry():
    expires = 1_790_000_000
    runner, fake = az_runner(
        lambda args: (0, f'{{"accessToken": "tok", "expires_on": {expires}}}', "")
    )
    token = AzureCliCredential(runner).get_token(GRAPH, TENANT)
    assert token.token == "tok"
    assert token.expires_on == datetime.fromtimestamp(expires, UTC)
    args = fake.calls[0]
    assert args[:2] == ["account", "get-access-token"]
    assert args[args.index("--resource") + 1] == GRAPH
    assert args[args.index("--tenant") + 1] == TENANT


def test_azure_cli_falls_back_to_the_old_local_expiry_field():
    runner, _ = az_runner(
        lambda args: (0, '{"accessToken": "tok", "expiresOn": "2026-09-24 13:00:00.000000"}', "")
    )
    assert AzureCliCredential(runner).get_token(GRAPH, TENANT).expires_on.tzinfo is not None


def test_azure_cli_without_a_token_is_an_error():
    runner, _ = az_runner(lambda args: (0, '{"expires_on": 1}', ""))
    with pytest.raises(AzCliError, match="no accessToken"):
        AzureCliCredential(runner).get_token(GRAPH, TENANT)


# Client secret and workload identity ----------------------------------------------


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


# Managed identity ----------------------------------------------------------------


def mi_session(seen: list):
    def handler(request):
        seen.append(request)
        return (200, {"access_token": "mi-token", "expires_on": "1790000000"})

    session = fake_session(handler)[0]
    session.mount("http://", session.get_adapter("https://"))
    return session


def test_managed_identity_uses_imds_off_app_service():
    seen: list = []
    credential = ManagedIdentityCredential(CLIENT_ID, environ={}, session=mi_session(seen))
    token = credential.get_token(GRAPH, TENANT)
    assert token.token == "mi-token"
    assert token.expires_on == datetime.fromtimestamp(1_790_000_000, UTC)
    request = seen[0]
    assert request.url.startswith("http://169.254.169.254/metadata/identity/oauth2/token?")
    assert request.headers["Metadata"] == "true"
    query = parse_qs(urlsplit(request.url).query)
    assert query["resource"] == [GRAPH]
    assert query["client_id"] == [CLIENT_ID]
    assert "Authorization" not in request.headers


def test_managed_identity_uses_the_app_service_endpoint_when_published():
    seen: list = []
    environ = {"IDENTITY_ENDPOINT": "http://127.0.0.1:41000/msi/token", "IDENTITY_HEADER": "h"}
    credential = ManagedIdentityCredential(environ=environ, session=mi_session(seen))
    credential.get_token(GRAPH, TENANT)
    assert seen[0].url.startswith("http://127.0.0.1:41000/msi/token?")
    assert seen[0].headers["X-IDENTITY-HEADER"] == "h"
    assert credential.source == "App Service"


# The factory ---------------------------------------------------------------------


def profile(**overrides) -> Profile:
    return Profile("p", TENANT, **overrides)


def test_the_factory_builds_each_method():
    runner, _ = az_runner(lambda args: (0, "{}", ""))
    assert isinstance(credential_for(profile(), runner=runner), AzureCliCredential)
    secret = credential_for(
        profile(auth="client-secret", client_id=CLIENT_ID),
        environ={"AZURE_CLIENT_SECRET": "s"},
    )
    assert isinstance(secret, ClientSecretCredential)
    federated = credential_for(
        profile(auth="workload-identity", client_id=CLIENT_ID),
        environ={"AZURE_FEDERATED_TOKEN_FILE": "/var/run/token"},
    )
    assert isinstance(federated, WorkloadIdentityCredential)
    github = credential_for(
        profile(auth="workload-identity", client_id=CLIENT_ID),
        environ={
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.test/idtoken",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "t",
        },
    )
    assert isinstance(github, WorkloadIdentityCredential)
    managed = credential_for(profile(auth="managed-identity"), environ={})
    assert isinstance(managed, ManagedIdentityCredential)


@pytest.mark.parametrize(
    ("method", "hint"),
    [("client-secret", "AZURE_CLIENT_SECRET"), ("workload-identity", "AZURE_FEDERATED_TOKEN_FILE")],
)
def test_the_factory_explains_a_missing_secret_or_federated_token(method, hint):
    with pytest.raises(AuthError) as caught:
        credential_for(profile(auth=method, client_id=CLIENT_ID), environ={})
    assert hint in (caught.value.hint or "")
