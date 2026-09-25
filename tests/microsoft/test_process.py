import subprocess

import pytest

from fakes.azcli import az_runner
from fakes.ids import TENANT
from libre_devops_helpers.microsoft.process import (
    AzCliError,
    AzureCliRunner,
    clean_stderr,
    hint_for,
)


def test_run_json_adds_json_output_and_parses_it():
    runner, fake = az_runner(lambda args: (0, '{"a": 1}', ""))
    assert runner.run_json("account", "show") == {"a": 1}
    assert fake.calls[0] == ["account", "show", "--output", "json", "--only-show-errors"]
    assert fake.kwargs[0]["timeout"] == 120


def test_a_failure_carries_the_cleaned_message_and_a_sign_in_hint():
    runner, _ = az_with_error("ERROR: AADSTS700082: The refresh token has expired")
    with pytest.raises(AzCliError, match="AADSTS700082") as caught:
        runner.run_json("account", "get-access-token")
    assert "az account get-access-token failed" in str(caught.value)
    assert "sign in again" in (caught.value.hint or "")


def az_with_error(stderr: str):
    return az_runner(lambda args: (1, "", stderr))


def test_an_unexpected_failure_drops_the_traceback_and_hints_at_the_tenant():
    # The shape az prints when the tenant does not exist.
    stderr = (
        "ERROR: The command failed with an unexpected error. Here is the traceback:\n"
        f"ERROR: Unable to get authority configuration for https://login.microsoftonline.com/{TENANT}.\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/az/lib/python3.14/site-packages/msal/authority.py", line 98, in __init__\n'
        "ValueError: OIDC Discovery failed\n"
    )
    assert clean_stderr(stderr) == (
        f"Unable to get authority configuration for https://login.microsoftonline.com/{TENANT}."
    )
    assert "tenant id" in (hint_for(clean_stderr(stderr)) or "")


def test_non_json_output_is_reported():
    runner, _ = az_runner(lambda args: (0, "not json", ""))
    with pytest.raises(AzCliError, match="did not return JSON"):
        runner.run_json("account", "show")


def test_a_timeout_is_reported():
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)

    with pytest.raises(AzCliError, match="timed out"):
        AzureCliRunner("az", runner=slow).run("account", "show")


def test_missing_az_is_reported(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(AzCliError, match="not on PATH"):
        AzureCliRunner().run("account", "show")


def test_az_runs_on_the_same_network_as_ldo(monkeypatch):
    from libre_devops_helpers.core import network

    runner, fake = az_runner(lambda args: (0, "{}", ""))
    runner.run_json("account", "show")
    env = fake.kwargs[0]["env"]
    assert env["REQUESTS_CA_BUNDLE"] == network.ca_bundle().path
    assert "HTTPS_PROXY" not in env
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    runner.run("login", interactive=True, env={"AZURE_CONFIG_DIR": "/tmp/az"})
    env = fake.kwargs[1]["env"]
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:3129"
    assert "localhost" in env["NO_PROXY"]  # az login's browser redirect lands on localhost
    assert env["AZURE_CONFIG_DIR"] == "/tmp/az"  # a caller's own settings are kept
