import json

from fakes.azcli import account_json, az_runner
from fakes.ids import OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.process import FakeRunner
from libre_devops_helpers.microsoft.azcli import (
    AzCli,
)
from libre_devops_helpers.microsoft.azcli.client import Account


def ok(value: object) -> tuple[int, str, str]:
    return (0, json.dumps(value), "")


def az_with(respond) -> tuple[AzCli, FakeRunner]:
    runner, fake = az_runner(respond)
    return AzCli(runner), fake


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
