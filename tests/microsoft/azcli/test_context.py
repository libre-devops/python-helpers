import json

import pytest

from fakes.azcli import FakeAzState, account_json
from fakes.ids import OTHER_SUBSCRIPTION, OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.process import FakeRunner
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


def az_state(state) -> AzCli:
    return AzCli(AzureCliRunner("az", runner=FakeRunner(state)))


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
