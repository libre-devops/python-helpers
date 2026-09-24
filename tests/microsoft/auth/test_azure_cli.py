import json
from datetime import UTC, datetime

import pytest

from fakes.azcli import FakeAzState, account_json, az_runner
from fakes.ids import SUBSCRIPTION, TENANT
from libre_devops_helpers.core.errors import ReauthRequired
from libre_devops_helpers.microsoft.auth import (
    AzureCliCredential,
)
from libre_devops_helpers.microsoft.process import AzCliError

GRAPH = "https://graph.microsoft.com"


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


@pytest.mark.parametrize(
    "reply",
    [{"accessToken": "t"}, {"accessToken": "t", "expiresOn": "not a time"}],
)
def test_azure_cli_without_a_usable_expiry_is_an_error(reply):
    runner, _ = az_runner(lambda args: (0, json.dumps(reply), ""))
    with pytest.raises(AzCliError, match="no usable expiry"):
        AzureCliCredential(runner).get_token("https://graph.microsoft.com", TENANT)


def test_azure_cli_accepts_expires_on_as_a_string():
    reply = {"accessToken": "t", "expires_on": "1790000000"}
    runner, _ = az_runner(lambda args: (0, json.dumps(reply), ""))
    token = AzureCliCredential(runner).get_token("https://graph.microsoft.com", TENANT)
    assert token.expires_on == datetime.fromtimestamp(1790000000, UTC)


def test_a_lapsed_sign_in_says_why_and_how_to_sign_in_again():
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)], lapsed=(TENANT,))
    with pytest.raises(ReauthRequired) as caught:
        AzureCliCredential(az_runner(state)[0]).get_token(GRAPH, TENANT)
    error = caught.value
    assert error.tenant_id == TENANT
    assert "sign-in frequency" in (error.reason or "")
    assert "sign-in frequency" in str(error)
    assert f"az login --tenant {TENANT}" in (error.hint or "")


def test_reauthenticate_signs_in_again_and_the_token_is_fetched_once_more():
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)], lapsed=(TENANT,))
    asked: list[tuple[str, str]] = []

    def reauthenticate(tenant_id: str, reason: str) -> bool:
        asked.append((tenant_id, reason))
        state(["login", "--tenant", tenant_id])
        return True

    credential = AzureCliCredential(az_runner(state)[0], reauthenticate=reauthenticate)
    token = credential.get_token(GRAPH, TENANT)
    assert token.tenant_id == TENANT
    assert [tenant for tenant, _ in asked] == [TENANT]
    fetches = [call for call in state.calls if call[:2] == ["account", "get-access-token"]]
    assert len(fetches) == 2


def test_declining_to_sign_in_again_is_still_an_error():
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)], lapsed=(TENANT,))
    credential = AzureCliCredential(az_runner(state)[0], reauthenticate=lambda t, r: False)
    with pytest.raises(ReauthRequired):
        credential.get_token(GRAPH, TENANT)


def test_other_az_failures_are_not_mistaken_for_a_lapse():
    runner, _ = az_runner(lambda args: (1, "", "ERROR: Unable to get authority configuration"))
    asked: list[str] = []
    credential = AzureCliCredential(runner, reauthenticate=lambda t, r: asked.append(t) or True)
    with pytest.raises(AzCliError, match="authority"):
        credential.get_token(GRAPH, TENANT)
    assert asked == []
