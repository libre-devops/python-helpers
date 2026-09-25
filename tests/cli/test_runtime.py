import threading
from urllib.parse import urlsplit

import pytest

from fakes.azcli import FakeAzState, account_json, az_runner
from fakes.http import form_body, routes
from fakes.ids import OTHER_SUBSCRIPTION, OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.tenant import invoke, run, runner
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import ReauthRequired
from libre_devops_helpers.microsoft.process import AzCliError


def test_a_client_secret_profile_gets_its_token_from_entra_not_az(config_file, tenant):
    result = invoke(
        config_file,
        tenant,
        ["entra", "token", "graph", "-p", "app", "-o", "json"],
        environ={"AZURE_CLIENT_SECRET": "s3cret"},
    )
    assert result.exit_code == 0, result.output
    login = next(
        r for r in tenant.requests if urlsplit(r.url).hostname == "login.microsoftonline.com"
    )
    assert form_body(login)["client_secret"] == "s3cret"
    assert "s3cret" not in result.output


def test_a_client_secret_profile_without_the_secret_says_what_to_set(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "token", "graph", "-p", "app"])
    assert result.exit_code == 1
    assert "AZURE_CLIENT_SECRET" in (result.exception.hint or "")


def test_without_a_default_profile_the_azure_cli_account_is_used(tmp_path):
    state = FakeAzState([account_json(SUBSCRIPTION, TENANT)], SUBSCRIPTION)
    obj = Runtime(config_path=tmp_path / "missing.toml", az_runner=az_runner(state)[0])
    profile = obj.microsoft.profile(None)
    assert (profile.name, profile.tenant_id, profile.subscription_id) == (
        "az-active",
        TENANT,
        SUBSCRIPTION,
    )


def test_a_tenant_level_account_has_no_subscription(tmp_path):
    state = FakeAzState([account_json(TENANT, TENANT, name="N/A(tenant level account)")], TENANT)
    obj = Runtime(config_path=tmp_path / "missing.toml", az_runner=az_runner(state)[0])
    assert obj.microsoft.profile(None).subscription_id is None


def test_without_a_profile_or_a_signed_in_cli_says_what_to_do(tmp_path):
    obj = Runtime(config_path=tmp_path / "missing.toml", az_runner=az_runner(FakeAzState([]))[0])
    with pytest.raises(AzCliError, match="not signed in") as caught:
        obj.microsoft.profile(None)
    assert "--profile" in (caught.value.hint or "")


# A lapsed Azure CLI sign-in ----------------------------------------------------------

REAUTH = brand.env_var("REAUTH")
SUBSCRIPTIONS = (
    200,
    {"value": [{"subscriptionId": SUBSCRIPTION, "displayName": "prod", "tenantId": TENANT}]},
)


def lapsed_state() -> FakeAzState:
    """Signed in to two tenants, active in the other one, with TENANT's sign-in lapsed."""
    known = [account_json(SUBSCRIPTION, TENANT), account_json(OTHER_SUBSCRIPTION, OTHER_TENANT)]
    return FakeAzState(known, OTHER_SUBSCRIPTION, lapsed=(TENANT,))


def answers(*replies: bool):
    asked: list[str] = []

    def confirm(question: str) -> bool:
        asked.append(question)
        return replies[len(asked) - 1]

    return confirm, asked


def test_a_lapsed_sign_in_without_a_terminal_is_an_error_that_names_the_cause(profiles_config):
    state = lapsed_state()
    result = run(profiles_config, routes({}), ["azure", "subscriptions"], az=state)
    assert isinstance(result.exception, ReauthRequired)
    assert "sign-in frequency" in str(result.exception)
    assert not state.logins


def test_on_a_terminal_it_signs_in_again_and_puts_the_active_account_back(profiles_config):
    state = lapsed_state()
    confirm, asked = answers(True)
    handler = routes({"/subscriptions": SUBSCRIPTIONS})
    result = run(profiles_config, handler, ["azure", "subscriptions"], az=state, confirm=confirm)
    assert result.exit_code == 0, result.output
    assert "prod" in result.stdout
    assert len(asked) == 1
    assert TENANT in asked[0]
    assert "sign-in frequency" in asked[0]
    assert state.logins[0][:3] == ["login", "--tenant", TENANT]
    assert "--allow-no-subscriptions" in state.logins[0]
    assert "--use-device-code" not in state.logins[0]
    assert state.active == OTHER_SUBSCRIPTION  # az login moved it; it was put back


def test_declining_to_sign_in_again_leaves_the_error(profiles_config):
    state = lapsed_state()
    confirm, _ = answers(False)
    result = run(profiles_config, routes({}), ["azure", "subscriptions"], az=state, confirm=confirm)
    assert isinstance(result.exception, ReauthRequired)
    assert not state.logins


def test_reauth_off_never_asks(profiles_config):
    state = lapsed_state()
    confirm, asked = answers(True)
    args = ["azure", "subscriptions"]
    result = run(
        profiles_config, routes({}), args, az=state, confirm=confirm, environ={REAUTH: "off"}
    )
    assert isinstance(result.exception, ReauthRequired)
    assert asked == []


def test_reauth_device_code_signs_in_with_a_device_code(profiles_config):
    state = lapsed_state()
    confirm, _ = answers(True)
    handler = routes({"/subscriptions": SUBSCRIPTIONS})
    environ = {REAUTH: "device-code"}
    args = ["azure", "subscriptions"]
    result = run(profiles_config, handler, args, az=state, confirm=confirm, environ=environ)
    assert result.exit_code == 0, result.output
    assert "--use-device-code" in state.logins[0]


def test_a_worker_thread_is_never_asked(tmp_path):
    state = lapsed_state()
    confirm, asked = answers(True)
    obj = Runtime(config_path=tmp_path / "missing.toml", az_runner=az_runner(state)[0])
    obj.interactive, obj.confirm = (lambda: True), confirm
    outcome: list[bool] = []
    worker = threading.Thread(
        target=lambda: outcome.append(obj.microsoft._reauthenticate(TENANT, "test"))
    )
    worker.start()
    worker.join()
    assert outcome == [False]
    assert asked == []


def test_the_config_files_network_settings_apply_to_every_call(tmp_path):
    from libre_devops_helpers.cli import app
    from libre_devops_helpers.core import network

    config = tmp_path / "config.toml"
    config.write_text('proxy = "127.0.0.1:3129"\nno_proxy = [".corp.example"]\n', "utf-8")
    result = runner.invoke(app, ["--config", str(config), "config", "path"])
    assert result.exit_code == 0, result.output
    assert network.settings().proxy == "http://127.0.0.1:3129"
    assert network.settings().no_proxy == (".corp.example",)


def test_a_broken_config_file_does_not_stop_a_command_that_does_not_need_it(tmp_path):
    from libre_devops_helpers.cli import app
    from libre_devops_helpers.core import network

    config = tmp_path / "config.toml"
    config.write_text('proxy = "socks5://x:1"\n', "utf-8")
    result = runner.invoke(app, ["--config", str(config), "json"], input='{"a": 1}')
    assert result.exit_code == 0, result.output
    assert network.settings() == network.NetworkSettings()
