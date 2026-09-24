import json

import pytest

from fakes import (
    OTHER_SUBSCRIPTION,
    OTHER_TENANT,
    SUBSCRIPTION,
    TENANT,
    FakeRunner,
    account_json,
    az_runner,
)
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.microsoft.azcli import (
    AzCli,
    find_account,
    match_profile,
    switch_profile,
)
from libre_devops_helpers.microsoft.azcli.client import Account
from libre_devops_helpers.microsoft.config import PLACEHOLDER_ID, Profile
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner

PROD = Profile("prod", TENANT, SUBSCRIPTION)
PROD_TENANT = Profile("prod-tenant", TENANT)
TEST_TENANT = Profile("test-tenant", OTHER_TENANT)


def ok(value: object) -> tuple[int, str, str]:
    return (0, json.dumps(value), "")


def az_with(respond) -> tuple[AzCli, FakeRunner]:
    runner, fake = az_runner(respond)
    return AzCli(runner), fake


def az_state(state) -> AzCli:
    return AzCli(AzureCliRunner("az", runner=FakeRunner(state)))


def test_current_account_parses_and_signed_out_is_none():
    az, _ = az_with(lambda args: ok(account_json(SUBSCRIPTION, TENANT, default=True)))
    account = az.current_account()
    assert account == Account(SUBSCRIPTION, "sub", TENANT, "Enabled", True, "analyst@example.com")

    az, _ = az_with(lambda args: (1, "", "ERROR: Please run 'az login' to setup account."))
    assert az.current_account() is None


def test_login_is_interactive_and_skips_the_cli_subscription_picker():
    az, runner = az_with(lambda args: (0, "", ""))
    az.login(OTHER_TENANT, device_code=True, allow_no_subscriptions=True)
    assert runner.calls[0][:3] == ["login", "--tenant", OTHER_TENANT]
    assert {"--use-device-code", "--allow-no-subscriptions"} <= set(runner.calls[0])
    assert runner.kwargs[0]["capture_output"] is False
    assert runner.kwargs[0]["env"]["AZURE_CORE_LOGIN_EXPERIENCE_V2"] == "off"


def accounts(*items: dict) -> list[Account]:
    return [Account.from_json(item) for item in items]


def test_find_account_for_a_subscription_needs_that_subscription():
    known = accounts(account_json(OTHER_SUBSCRIPTION, TENANT))
    assert find_account(known, PROD) is None
    known = accounts(account_json(SUBSCRIPTION, TENANT))
    assert find_account(known, PROD).id == SUBSCRIPTION


def test_find_account_for_a_tenant_keeps_the_active_account_first():
    known = accounts(
        account_json(TENANT, TENANT, name="N/A(tenant level account)"),
        account_json(SUBSCRIPTION, TENANT, default=True),
    )
    assert find_account(known, PROD_TENANT).id == SUBSCRIPTION
    known = accounts(
        account_json(OTHER_SUBSCRIPTION, TENANT), account_json(TENANT, TENANT, name="tenant")
    )
    assert find_account(known, PROD_TENANT).tenant_level


def test_match_profile_prefers_the_subscription_profile():
    account = accounts(account_json(SUBSCRIPTION, TENANT))[0]
    assert match_profile([PROD_TENANT, PROD], account) == PROD
    other = accounts(account_json(OTHER_SUBSCRIPTION, TENANT))[0]
    assert match_profile([PROD_TENANT, PROD], other) == PROD_TENANT


class FakeAzState:
    """Enough of az's account state to exercise switch_profile end to end."""

    def __init__(self, known: list[dict]) -> None:
        self.known = known
        self.active: str | None = None
        self.logins: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["account", "list"]:
            return ok(self.known)
        if args[:2] == ["account", "set"]:
            self.active = args[3]
            return (0, "", "")
        if args[:2] == ["account", "show"]:
            match = next(item for item in self.known if item["id"] == self.active)
            return ok({**match, "isDefault": True})
        if args[0] == "login":
            self.logins.append(args)
            tenant = args[2]
            self.known.append(account_json(tenant, tenant, name="N/A(tenant level account)"))
            return (0, "", "")
        raise AssertionError(f"unexpected az call: {args}")


def test_switch_uses_an_existing_session_without_signing_in():
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)])
    result = switch_profile(az_state(state), PROD)
    assert result.account.id == SUBSCRIPTION
    assert not result.signed_in
    assert state.logins == []


def test_switch_signs_in_to_a_tenant_without_a_session():
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)])
    result = switch_profile(az_state(state), TEST_TENANT)
    assert result.signed_in
    assert result.account.tenant_id == OTHER_TENANT
    assert "--allow-no-subscriptions" in state.logins[0]


def test_switch_without_sign_in_fails_instead_of_prompting():
    state = FakeAzState([])
    with pytest.raises(AzCliError, match="no session"):
        switch_profile(az_state(state), TEST_TENANT, sign_in=False)
    assert state.logins == []


def test_switch_refuses_placeholder_profiles():
    with pytest.raises(ConfigError, match="placeholder"):
        switch_profile(az_state(FakeAzState([])), Profile("x", PLACEHOLDER_ID))
