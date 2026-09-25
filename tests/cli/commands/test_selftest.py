import json

import pytest
import typer

from fakes.tenant import runner
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.commands import pretty, selftest
from libre_devops_helpers.cli.commands.selftest import Case
from libre_devops_helpers.core import brand


@pytest.fixture
def cases(monkeypatch):
    """A short battery that needs no network: json, and what makes it misbehave."""

    def use(*chosen: Case) -> None:
        monkeypatch.setattr(selftest, "CASES", chosen)

    return use


def test_each_outcome_is_named_and_a_crash_says_where(cases, monkeypatch, tmp_path):
    cases(
        Case(("json",), stdin="{}"),  # ok
        Case(("json", "--no-such-option")),  # usage
        Case(("json", "--indent", "2"), stdin="not json"),  # refused: the input is explained
        Case(("json", "--compact"), stdin="{}"),  # attention, below
        Case(("json", "--sort-keys"), stdin="{}"),  # crash, below
    )
    real = pretty._documents
    calls = {"n": 0}

    def documents(text):
        calls["n"] += 1
        if calls["n"] == 3:
            raise typer.Exit(3)
        if calls["n"] == 4:
            raise RuntimeError("boom")
        return real(text)

    monkeypatch.setattr(pretty, "_documents", documents)
    report = tmp_path / "self-test.json"
    result = runner.invoke(app, ["self-test", "--report", str(report), "-o", "json"])
    assert result.exit_code == 1  # a crash and a usage error are both bugs
    outcomes = {item["command"]: item for item in json.loads(result.stdout)}
    assert {command: item["result"] for command, item in outcomes.items()} == {
        "json": "ok",
        "json --no-such-option": "usage",
        "json --indent 2": "refused",
        "json --compact": "attention",
        "json --sort-keys": "CRASH",
    }
    crash = outcomes["json --sort-keys"]
    assert crash["detail"] == "RuntimeError: boom"
    assert crash["where"]
    assert "not JSON" in outcomes["json --indent 2"]["detail"]
    assert json.loads(report.read_text()) == json.loads(result.stdout)
    assert "1 CRASH" in result.stderr


def test_an_explained_error_is_refused_with_its_hint(cases, tmp_path):
    cases(Case(("profiles",)))
    missing = tmp_path / "none.toml"
    result = runner.invoke(app, ["--config", str(missing), "self-test", "-o", "json"])
    assert result.exit_code == 0, result.output
    (outcome,) = json.loads(result.stdout)
    assert outcome["result"] == "refused"
    assert "config file not found" in outcome["detail"]
    assert outcome["hint"] == "create one with 'ldo config init'"


def test_the_table_is_followed_by_each_failure_in_full(cases, tmp_path):
    cases(Case(("json",), stdin="{}"), Case(("profiles",)))
    missing = tmp_path / "none.toml"
    result = runner.invoke(app, ["--config", str(missing), "self-test"])
    assert result.exit_code == 0, result.output
    table, details = result.stdout.split("\n\n", 1)
    assert "COMMAND" in table
    lines = [" ".join(line.split()) for line in details.splitlines()]
    assert lines[0] == f"refused: {brand.COMMAND} profiles"
    assert lines[1].startswith("Said config file not found")
    assert lines[2] == f"Hint create one with {brand.command('config init')}"
    assert "json" not in details  # only failures are shown in full


def test_names_fill_the_commands_and_cases_without_them_are_skipped(cases, monkeypatch):
    seen = []

    def run(args, stdin, config, profile):
        seen.append(" ".join(args))
        return selftest.Outcome(" ".join(args), "ok", 0, 0.0)

    monkeypatch.setattr(selftest, "_run", run)
    cases(
        Case(("xdr", "machines", "{device}"), ("device",)),
        Case(("xdr", "machines", "{short}"), ("device",)),
        Case(("entra", "user-groups", "{user}"), ("user",)),
        Case(("entra", "app-credentials"), slow=True),
        Case(("azure", "subscriptions")),
    )
    result = runner.invoke(app, ["self-test", "--device", "app07.corp.example"])
    assert result.exit_code == 0, result.output
    assert seen == ["xdr machines app07.corp.example", "xdr machines app07", "azure subscriptions"]
    seen.clear()
    runner.invoke(
        app, ["self-test", "--device", "app07", "--all", "--only", "xdr", "--only", "entra"]
    )
    assert seen == ["xdr machines app07", "entra app-credentials"]  # the short one, once


def test_the_cases_left_out_for_want_of_a_name_are_counted_with_their_options(cases, monkeypatch):
    monkeypatch.setattr(selftest, "_run", lambda *args: selftest.Outcome("x", "ok", 0, 0.0))
    cases(
        Case(("xdr", "machines", "{device}"), ("device",)),
        Case(("logs", "ingestion", "-w", "{workspace}"), ("workspace",)),
        Case(("entra", "user-groups", "{user}"), ("user",), slow=True),
        Case(("azure", "subscriptions")),
    )
    result = runner.invoke(app, ["self-test"])
    assert "2 more need --device, --workspace: give them to run those too" in result.stderr
    result = runner.invoke(app, ["self-test", "--all", "--device", "web01", "--only", "entra"])
    assert "1 more need --user" in result.stderr


def test_a_command_that_exits_1_is_explained_by_its_warnings_not_its_summary():
    output = (
        "warning: cannot read vault kv-app: HTTP 403 Forbidden\n"
        "hint: the resource's firewall does not allow this machine's IP address\n"
        "warning: cannot read vault kv-ops: HTTP 403 Forbidden\n"
        "hint: the resource's firewall does not allow this machine's IP address\n"
        "0 item(s) expire within 30d (0 checked in 0 of 2 vault(s))\n"
    )
    said, hint = selftest._explanation(output)
    assert said.splitlines() == [
        "warning: cannot read vault kv-app: HTTP 403 Forbidden",
        "warning: cannot read vault kv-ops: HTTP 403 Forbidden",
    ]
    assert hint == "the resource's firewall does not allow this machine's IP address"
    assert selftest._explanation("3 row(s)\n") == ("3 row(s)", None)


def test_several_warnings_are_one_row_in_the_table_and_each_in_the_details(cases, monkeypatch):
    def run(args, stdin, config, profile):
        detail = "warning: cannot read vault kv-app\nwarning: cannot read vault kv-ops"
        return selftest.Outcome("keyvault expiry", "refused", 1, 0.1, detail, "check the firewall")

    monkeypatch.setattr(selftest, "_run", run)
    cases(Case(("keyvault", "expiry", "kv-app")))
    result = runner.invoke(app, ["self-test"])
    table, details = result.stdout.split("\n\n", 1)
    assert "warning: cannot read vault kv-app (and 1 more)" in table
    lines = [" ".join(line.split()) for line in details.splitlines()]
    assert lines[1:] == [
        "Said warning: cannot read vault kv-app",
        "Said warning: cannot read vault kv-ops",
        "Hint check the firewall",
    ]


def test_the_profile_is_given_to_every_command_and_put_back(cases, monkeypatch):
    seen = []
    real = pretty._documents

    def documents(text):
        import os

        seen.append(os.environ.get("LDO_PROFILE"))
        return real(text)

    monkeypatch.setattr(pretty, "_documents", documents)
    monkeypatch.delenv("LDO_PROFILE", raising=False)
    cases(Case(("json",), stdin="{}"))
    result = runner.invoke(app, ["self-test", "-p", "work"])
    assert result.exit_code == 0, result.output
    assert seen == ["work"]
    import os

    assert "LDO_PROFILE" not in os.environ


def test_the_battery_reaches_only_what_it_is_given():
    # A Key Vault sweep sends a request as the person to every vault in the tenant; each one
    # they cannot read refuses and logs it, which looks like reconnaissance.
    for case in selftest.CASES:
        assert "--all-vaults" not in case.args, case.args


def test_the_battery_is_read_only_and_every_command_in_it_exists():
    from typer.testing import CliRunner

    writes = {"az use", "config init", "snow sign-in", "snow sign-out", "entra sign-out"}
    for case in selftest.CASES:
        line = " ".join(case.args)
        assert not any(line.startswith(write) for write in writes), line
        names = {"device": "web01", "short": "web01", "user": "u", "group": "g", "snow": ""}
        filled = [part.format(**names, workspace="w", vault="kv-app") for part in case.args]
        result = CliRunner().invoke(app, [*filled, "--help"])
        assert result.exit_code == 0, (line, result.output)
