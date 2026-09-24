import json
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
