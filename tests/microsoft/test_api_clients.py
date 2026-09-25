import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError
from libre_devops_helpers.microsoft.api_clients import ArmServiceClient, GraphServiceClient
from libre_devops_helpers.microsoft.clouds import USGOV
from libre_devops_helpers.microsoft.config import Profile


class Directory(GraphServiceClient):
    API_NAME = "Directory (Microsoft Graph)"


class Resources(ArmServiceClient):
    pass


def test_a_graph_client_follows_the_profiles_cloud_and_names_its_api_in_errors():
    session, adapter = fake_session(lambda request: (403, {"error": {"code": "Forbidden"}}))
    tokens = StaticTokens()
    profile = Profile(name="gov", tenant_id=TENANT, cloud=USGOV)
    with Directory.for_profile(profile, tokens, session=session) as client:
        assert isinstance(client, Directory)
        with pytest.raises(ApiError, match=r"^Directory \(Microsoft Graph\): HTTP 403"):
            client.api.get("/v1.0/me")
    assert adapter.requests[0].url.startswith(USGOV.graph_url)
    assert tokens.calls == [(USGOV.graph_url, TENANT)]


def test_a_resource_manager_client_asks_for_tokens_with_the_trailing_slash():
    session, _ = fake_session(lambda request: (200, {"value": []}))
    tokens = StaticTokens()
    client = Resources.create(tokens, TENANT, session=session)
    client.api.get("/subscriptions", params={"api-version": "2022-12-01"})
    assert tokens.calls == [("https://management.azure.com/", TENANT)]
    assert client.api.name == "Azure Resource Manager"
    client.close()
