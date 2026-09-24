import json
import re
import runpy

import pytest

from fakes.tenant import invoke, runner
from libre_devops_helpers import cli
from libre_devops_helpers.cli import app
from libre_devops_helpers.core import brand


def test_otlp_log_lines_go_to_stderr(config_file, tenant):
    result = invoke(
        config_file, tenant, ["-vv", "--log-format", "otlp", "xdr", "machines", "web01"]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stderr.splitlines() if line.startswith("{")]
    assert lines
    record = json.loads(lines[0])["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["severityText"] == "DEBUG"
    assert "eyJ" not in result.stderr


def test_ldo_log_level_from_the_environment_turns_on_logging(config_file, tenant, monkeypatch):
    monkeypatch.setenv("LDO_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LDO_LOG_FORMAT", "OtlpIndented")
    result = invoke(config_file, tenant, ["xdr", "machines", "web01"])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stderr.splitlines() if line.startswith('{"resourceLogs"')]
    assert lines


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("ldo ")


def test_the_package_runs_as_a_module(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["python -m", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module(cli.__name__.rsplit(".", 1)[0], run_name="__main__")
    assert caught.value.code == 0
    assert capsys.readouterr().out.startswith(f"{brand.COMMAND} ")


def test_main_prints_library_errors_with_hint_and_exit_code(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["ldo", "--config", str(tmp_path / "x.toml"), "profiles"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert "error: config file not found" in err
    assert "hint: create one with 'ldo config init'" in err


def commands():
    """Every command and group, with its path, e.g. (["entra", "devices"], command)."""
    import typer

    found = []

    def walk(command, path):
        found.append((path, command))
        for name, sub in (getattr(command, "commands", None) or {}).items():
            walk(sub, [*path, name])

    walk(typer.main.get_command(app), [])
    return found


def test_help_text_survives_markdown_rendering():
    # Help is rendered as markdown (so paragraphs reflow), which drops <tags> and turns
    # *stars* into emphasis: keep both out of help text.
    for path, command in commands():
        texts = [command.help or "", *[getattr(p, "help", None) or "" for p in command.params]]
        for text in texts:
            assert "<" not in text, path
            assert not re.search(r"(^|\s)\*\S", text), path


def test_every_command_has_help_that_renders():
    found = commands()
    assert len(found) > 80
    for path, _ in found:
        result = runner.invoke(app, [*path, "--help"])
        assert result.exit_code == 0, (path, result.output)


def test_in_otlp_mode_stderr_is_nothing_but_otlp_json_lines(config_file, tenant):
    args = ["--log-format", "otlp", "--log-level", "info", "xdr", "machines", "web01,ghost"]
    result = invoke(config_file, tenant, args)
    assert result.exit_code == 3, result.output
    lines = result.stderr.splitlines()
    assert lines
    bodies = []
    for line in lines:
        record = json.loads(line)["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        bodies.append(record["body"]["stringValue"])
    assert any("1 of 2 found in Defender" in body for body in bodies)  # the note, as a record


def test_an_error_in_otlp_mode_is_an_error_record_with_its_hint(monkeypatch, capsys, tmp_path):
    argv = ["ldo", "--log-format", "otlp", "--config", str(tmp_path / "x.toml"), "profiles"]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit):
        cli.main()
    (line,) = capsys.readouterr().err.splitlines()
    record = json.loads(line)["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["severityText"] == "ERROR"
    assert record["body"]["stringValue"].startswith("config file not found")
    attributes = {item["key"]: item["value"]["stringValue"] for item in record["attributes"][2:]}
    assert attributes["hint"] == "create one with 'ldo config init'"
