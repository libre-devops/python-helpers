import json
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest
from typer.testing import CliRunner

from fakes import (
    OTHER_TENANT,
    SUBSCRIPTION,
    TENANT,
    account_json,
    az_runner,
    fake_session,
    graph_claims,
    make_jwt,
)
from libre_devops_helpers import cli
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.runtime import Runtime

CONFIG = f"""
[microsoft]
default_profile = "prod-tenant"

[microsoft.profiles.prod]
tenant_id = "{TENANT}"
subscription_id = "{SUBSCRIPTION}"

[microsoft.profiles.prod-tenant]
tenant_id = "{TENANT}"

[microsoft.profiles.test-tenant]
tenant_id = "{OTHER_TENANT}"
"""

runner = CliRunner()


def az_responder(args: list[str]) -> tuple[int, str, str]:
    if args[:2] == ["account", "list"]:
        return (0, json.dumps([account_json(SUBSCRIPTION, TENANT, default=True)]), "")
    if args[:2] == ["account", "get-access-token"]:
        resource = args[args.index("--resource") + 1]
        token = make_jwt(graph_claims(aud=resource.rstrip("/")))
        expires = int(datetime.now(UTC).timestamp()) + 3600
        return (0, json.dumps({"accessToken": token, "expires_on": expires}), "")
    raise AssertionError(f"unexpected az call: {args}")


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def runtime(config_path, handler=None, environ=None) -> Runtime:
    session = fake_session(handler)[0] if handler else None
    return Runtime(
        config_path=config_path,
        az_runner=az_runner(az_responder)[0],
        session=session,
        environ=environ or {},
    )


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("ldo ")


def test_config_init_writes_the_template_once(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    result = runner.invoke(app, ["--config", str(path), "config", "init"])
    assert result.exit_code == 0, result.output
    assert "[microsoft.profiles.test-tenant]" in path.read_text()
    again = runner.invoke(app, ["--config", str(path), "config", "init"])
    assert "already exists" in str(again.exception)
    forced = runner.invoke(app, ["--config", str(path), "config", "init", "--force"])
    assert forced.exit_code == 0


def test_profiles_marks_the_active_profile_and_sessions(config_file):
    result = runner.invoke(app, ["profiles", "-o", "json"], obj=runtime(config_file))
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.stdout)}
    assert rows["prod"]["active"]
    assert rows["prod-tenant"]["default"]
    assert rows["prod-tenant"]["signed_in"]
    assert rows["test-tenant"]["signed_in"] is False


def test_profiles_table_is_readable(config_file):
    result = runner.invoke(app, ["profiles"], obj=runtime(config_file))
    assert result.exit_code == 0, result.output
    assert "prod-tenant (default)" in result.stdout
    assert "SIGNED IN" in result.stdout


def test_token_checks_pass_and_raw_prints_only_the_token(config_file):
    result = runner.invoke(app, ["entra", "token", "graph", "-o", "json"], obj=runtime(config_file))
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["valid"]
    assert report["claims"]["tid"] == TENANT

    raw = runner.invoke(app, ["entra", "token", "graph", "--raw"], obj=runtime(config_file))
    assert raw.exit_code == 0
    assert raw.stdout.strip().count(".") == 2


def test_token_for_the_wrong_tenant_fails(config_file):
    # az hands back a TENANT token, but test-tenant expects OTHER_TENANT.
    result = runner.invoke(
        app, ["entra", "token", "graph", "-p", "test-tenant"], obj=runtime(config_file)
    )
    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_inspect_token_reads_stdin():
    token = make_jwt(graph_claims())
    result = runner.invoke(
        app, ["entra", "inspect-token", "--resource", "graph", "--tenant", TENANT], input=token
    )
    assert result.exit_code == 0, result.output
    assert "analyst@example.com" in result.stdout
    assert token not in result.stdout


def test_inspect_token_rejects_empty_stdin():
    result = runner.invoke(app, ["entra", "inspect-token"], input="")
    assert result.exit_code == 1
    assert "no token on stdin" in str(result.exception)


def test_check_devices_splits_names_and_exits_3_when_one_is_missing(config_file):
    record = {
        "id": "a" * 40,
        "computerDnsName": "web01",
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": "2026-09-20T00:00:00Z",
    }

    def handler(request):
        found = "'web01'" in unquote(request.url)
        return (200, {"value": [record] if found else []})

    result = runner.invoke(
        app, ["xdr", "machines", "web01,ghost", "-o", "json"], obj=runtime(config_file, handler)
    )
    assert result.exit_code == 3, result.output
    lookups = json.loads(result.stdout)
    assert [(item["query"], item["found"]) for item in lookups] == [
        ("web01", True),
        ("ghost", False),
    ]


def test_device_groups_reports_a_missing_device(config_file):
    result = runner.invoke(
        app,
        ["entra", "device-groups", "ghost.corp.example.com"],
        obj=runtime(config_file, lambda request: (200, {"value": []})),
    )
    assert result.exit_code == 1
    assert "no Entra device is named 'ghost.corp.example.com' or 'ghost'" in str(result.exception)


def test_main_prints_library_errors_with_hint_and_exit_code(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["ldo", "--config", str(tmp_path / "x.toml"), "profiles"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert "error: config file not found" in err
    assert "hint: create one with 'ldo config init'" in err
