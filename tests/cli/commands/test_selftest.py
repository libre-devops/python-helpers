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


def test_the_battery_is_read_only_and_every_command_in_it_exists():
    from typer.testing import CliRunner

    writes = {"az use", "config init", "snow sign-in", "snow sign-out", "entra sign-out"}
    for case in selftest.CASES:
        line = " ".join(case.args)
        assert not any(line.startswith(write) for write in writes), line
        filled = [
            part.format(device="web01", short="web01", user="u", group="g", workspace="w", snow="")
            for part in case.args
        ]
        result = CliRunner().invoke(app, [*filled, "--help"])
        assert result.exit_code == 0, (line, result.output)
