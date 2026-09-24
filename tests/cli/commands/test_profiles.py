import json
import re

from fakes.http import routes
from fakes.ids import CLIENT_ID, TENANT
from fakes.tenant import run, runner, runtime
from libre_devops_helpers.cli import app
from libre_devops_helpers.microsoft.config import PLACEHOLDER_ID


def test_profiles_marks_the_active_profile_and_sessions(profiles_config):
    result = runner.invoke(app, ["profiles", "-o", "json"], obj=runtime(profiles_config))
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.stdout)}
    assert rows["prod"]["active"]
    assert rows["prod-tenant"]["default"]
    assert rows["prod-tenant"]["signed_in"]
    assert rows["test-tenant"]["signed_in"] is False


def test_profiles_table_is_readable(profiles_config):
    result = runner.invoke(app, ["profiles"], obj=runtime(profiles_config))
    assert result.exit_code == 0, result.output
    assert "prod-tenant (default)" in result.stdout
    assert "SIGNED IN" in result.stdout


def test_profiles_warn_when_az_accounts_cannot_be_read(profiles_config):
    def broken(args):
        return (1, "", "ERROR: something went wrong")

    result = run(profiles_config, routes({}), ["profiles", "-o", "json"], az=broken)
    assert result.exit_code == 0, result.output
    assert "cannot read Azure CLI accounts" in result.stderr
    assert {row["signed_in"] for row in json.loads(result.stdout)} == {None}


def test_profiles_flag_placeholders_other_clouds_and_app_profiles(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
[microsoft.profiles.gov]
tenant_id = "{TENANT}"
cloud = "usgov"

[microsoft.profiles.ci]
tenant_id = "{TENANT}"
auth = "client-secret"
client_id = "{CLIENT_ID}"

[microsoft.profiles.todo]
tenant_id = "{PLACEHOLDER_ID}"
""",
        encoding="utf-8",
    )
    result = run(config, routes({}), ["profiles"])
    assert result.exit_code == 0, result.output
    assert f"tenant {TENANT} (usgov)" in result.stdout
    assert "n/a" in result.stdout
    assert "placeholder ids in todo" in result.stderr


def test_a_config_without_profiles_says_how_to_add_them(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("# nothing yet\n", encoding="utf-8")
    result = run(config, routes({}), ["profiles"])
    assert result.exit_code == 0, result.output
    assert "no profiles configured" in result.stderr


def test_servicenow_profiles_are_listed_with_whether_they_can_sign_in(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[servicenow]
default_profile = "work"

[servicenow.profiles.work]
instance = "https://itsm.example.com"
client_id = "abc"
description = "work instance"

[servicenow.profiles.lab]
instance = "dev12345"
auth = "basic"
username = "admin"

[servicenow.profiles.desk]
instance = "dev54321"
client_id = "abc"
token_cache = "keychain"
""",
        encoding="utf-8",
    )
    environ = {"SNOW_INSTANCE_PASSWORD": "x"}
    result = run(config, routes({}), ["profiles", "-o", "json"], environ=environ)
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.stdout) if row["vendor"] == "servicenow"}
    assert rows["work"]["default"]
    assert rows["work"]["signed_in"] is False  # no kept sign-in yet
    assert rows["lab"]["signed_in"] is True  # basic, with the password set
    assert rows["desk"]["signed_in"] is None  # the keychain is not read for a listing
    table = run(config, routes({}), ["profiles"], environ=environ)
    rows = [re.split(r"\s{2,}", line.strip()) for line in table.stdout.splitlines()]
    work = next(cells for cells in rows if "work (default)" in cells)
    assert {"itsm.example.com", "oauth (browser)"} <= set(work)
