import json

from fakes.azcli import FakeAzState, account_json
from fakes.http import routes
from fakes.ids import OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.tenant import run
from libre_devops_helpers.microsoft.process import AzCliError


def test_use_switches_to_an_existing_session_without_signing_in(profiles_config):
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT, name="prod-sub")])
    result = run(profiles_config, routes({}), ["az", "use", "prod"], az=state)
    assert result.exit_code == 0, result.output
    assert state.active == SUBSCRIPTION
    assert not state.logins
    assert f"Switched to prod: prod-sub ({SUBSCRIPTION}) in tenant {TENANT}" in result.stdout
    assert "as analyst@example.com" in result.stdout


def test_use_signs_in_to_a_tenant_without_a_session(profiles_config):
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)])
    result = run(
        profiles_config, routes({}), ["az", "use", "test-tenant", "--device-code"], az=state
    )
    assert result.exit_code == 0, result.output
    assert state.logins[0][:3] == ["login", "--tenant", OTHER_TENANT]
    assert "--use-device-code" in state.logins[0]
    assert "tenant-level account" in result.stdout


def test_use_with_no_login_fails_rather_than_prompting(profiles_config):
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)])
    result = run(profiles_config, routes({}), ["az", "use", "test-tenant", "--no-login"], az=state)
    assert result.exit_code == 1
    assert not state.logins


def test_whoami_names_the_matching_profile(profiles_config):
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT, name="prod-sub")], SUBSCRIPTION)
    table = run(profiles_config, routes({}), ["az", "whoami"], az=state)
    assert table.exit_code == 0, table.output
    assert "prod-sub" in table.stdout
    record = json.loads(
        run(profiles_config, routes({}), ["az", "whoami", "-o", "json"], az=state).stdout
    )
    assert record == {
        "profile": "prod",
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "subscription_name": "prod-sub",
        "user": "analyst@example.com",
        "state": "Enabled",
    }


def test_whoami_when_signed_out_says_how_to_sign_in(profiles_config):
    result = run(profiles_config, routes({}), ["az", "whoami"], az=FakeAzState([]))
    assert isinstance(result.exception, AzCliError)
    assert "not signed in" in str(result.exception)
