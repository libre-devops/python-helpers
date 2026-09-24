from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from fakes.http import fake_session
from fakes.ids import CLIENT_ID, TENANT
from libre_devops_helpers.microsoft.auth import (
    ManagedIdentityCredential,
)

GRAPH = "https://graph.microsoft.com"


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
