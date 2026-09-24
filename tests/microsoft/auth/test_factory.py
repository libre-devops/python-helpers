import pytest

from fakes.azcli import az_runner
from fakes.ids import CLIENT_ID, TENANT
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.core.token_store import FILE_ENV, FileStore, MemoryStore
from libre_devops_helpers.microsoft.auth import (
    AzureCliCredential,
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
    credential_for,
)
from libre_devops_helpers.microsoft.config import Profile


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


def test_a_delegated_profile_keeps_its_sign_in_where_token_cache_says(tmp_path):
    environ = {FILE_ENV: str(tmp_path / "tokens.json")}
    kept = profile(auth="interactive", client_id=CLIENT_ID, token_cache="file")
    credential = credential_for(kept, environ=environ)
    assert isinstance(credential._store, FileStore)
    assert credential._store.path == tmp_path / "tokens.json"
    given = MemoryStore()
    assert credential_for(kept, environ=environ, token_store=given)._store is given
    # Without token_cache, a profile keeps its sign-in in the private file.
    default = credential_for(profile(auth="device-code", client_id=CLIENT_ID), environ=environ)
    assert isinstance(default._store, FileStore)
    memory = profile(auth="device-code", client_id=CLIENT_ID, token_cache="memory")
    assert isinstance(credential_for(memory, environ=environ)._store, MemoryStore)
