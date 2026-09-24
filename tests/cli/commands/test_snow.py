import json
import re

from fakes.servicenow import (
    CLIENT_ID,
    CLIENT_SECRET,
    INSTANCE,
    PASSWORD,
    USERNAME,
    FakeInstance,
    run,
)
from libre_devops_helpers.core.errors import ConfigError, ReauthRequired
from libre_devops_helpers.core.token_store import MemoryStore

BASIC = {
    "SNOW_INSTANCE_URL": INSTANCE,
    "SNOW_INSTANCE_USERNAME": USERNAME,
    "SNOW_INSTANCE_PASSWORD": PASSWORD,
}
OAUTH = {**BASIC, "SNOW_CLIENT_ID": CLIENT_ID, "SNOW_CLIENT_SECRET": CLIENT_SECRET}


def config(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_whoami_with_basic_from_the_environment():
    result = run(["snow", "whoami"], FakeInstance(), environ=BASIC)
    assert result.exit_code == 0, result.output
    assert "ana (Ana Analyst)" in result.stdout
    assert "admin, itil" in result.stdout
    assert re.search(r"^Sign-in\s+basic$", result.stdout, re.MULTILINE)


def test_whoami_as_json_says_which_features_the_roles_cover():
    result = run(["snow", "whoami", "-o", "json"], FakeInstance(), environ=BASIC)
    record = json.loads(result.stdout)
    assert record["roles"] == ["admin", "itil"]
    assert record["covers"] == {"instance release and applications": True}


def test_oauth_from_the_environment_signs_in_with_the_password_once():
    instance = FakeInstance()
    store = MemoryStore()
    first = run(["snow", "whoami"], instance, environ=OAUTH, store=store)
    assert first.exit_code == 0, first.output
    assert "oauth (password)" in first.stdout
    # The next command needs no password: the kept refresh token signs in.
    without_password = {
        key: value for key, value in OAUTH.items() if key != "SNOW_INSTANCE_PASSWORD"
    }
    second = run(["snow", "whoami"], instance, environ=without_password, store=store)
    assert second.exit_code == 0, second.output
    assert instance.grants == ["password", "refresh_token"]


def test_sign_in_in_a_browser_on_a_headless_machine(tmp_path):
    instance = FakeInstance()
    store = MemoryStore()
    path = config(
        tmp_path,
        f"""
[servicenow]
default_profile = "work"

[servicenow.profiles.work]
instance = "{INSTANCE}"
client_id = "{CLIENT_ID}"
""",
    )
    asked: list[str] = []
    shown: list[str] = []

    def paste(question, secret):
        asked.append(question)
        if "Client secret" in question:
            return CLIENT_SECRET
        # The fake person opens the link the command showed, and signs in.
        url = re.search(r"https://\S+/oauth_auth\.do\?\S+", shown[-1]).group(0)
        return instance.approve(url)

    result = run(
        ["snow", "sign-in"], instance, config=path, ask=paste, store=store, notify=shown.append
    )
    assert result.exit_code == 0, result.output
    assert "Signed in to dev12345.service-now.com as ana" in result.stderr
    assert "authorization_code" in instance.grants
    assert any("address you landed on" in question for question in asked)
    # Kept, with the typed-in secret, so later commands need nothing in the environment.
    later = run(["snow", "whoami"], instance, config=path, store=store)
    assert later.exit_code == 0, later.output


def test_without_a_kept_sign_in_and_no_terminal_it_says_to_sign_in(tmp_path):
    env = {
        "SNOW_INSTANCE_URL": INSTANCE,
        "SNOW_CLIENT_ID": CLIENT_ID,
        "SNOW_CLIENT_SECRET": CLIENT_SECRET,
    }
    result = run(["snow", "whoami"], FakeInstance(), environ=env)
    assert isinstance(result.exception, ReauthRequired)
    assert "snow sign-in -p env" in (result.exception.hint or "")


def test_token_shows_the_expiry_and_raw_prints_only_the_token():
    instance = FakeInstance()
    store = MemoryStore()
    result = run(["snow", "token", "-o", "json"], instance, environ=OAUTH, store=store)
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)
    assert record["sign_in_kept"] is True
    assert record["token_cache"] == "file"
    raw = run(["snow", "token", "--raw"], instance, environ=OAUTH, store=store)
    assert raw.stdout.strip() in instance.access


def test_token_for_a_basic_profile_explains_there_is_none():
    result = run(["snow", "token"], FakeInstance(), environ=BASIC)
    assert isinstance(result.exception, ConfigError)
    assert "has no token" in str(result.exception)


def test_sign_out_forgets_the_kept_sign_in():
    instance = FakeInstance()
    store = MemoryStore()
    run(["snow", "whoami"], instance, environ=OAUTH, store=store)
    result = run(["snow", "sign-out"], instance, environ=OAUTH, store=store)
    assert "Forgot the sign-in kept for env" in result.stderr
    again = run(["snow", "sign-out"], instance, environ=OAUTH, store=store)
    assert "No sign-in was kept" in again.stderr
    basic = run(["snow", "sign-out"], instance, environ=BASIC)
    assert "nothing is kept" in basic.stderr


def test_instance_reports_the_release_and_exits_3_without_sir():
    instance = FakeInstance()
    result = run(["snow", "instance"], instance, environ=BASIC)
    assert result.exit_code == 3, result.output
    assert "Zurich patch10" in result.stdout
    assert "not installed" in result.stdout
    assert "Activate Plugin" in result.stderr
    instance.tables["sys_db_object"].append({"name": "sn_si_incident"})
    installed = run(["snow", "instance", "-o", "json"], instance, environ=BASIC)
    assert installed.exit_code == 0, installed.output
    assert json.loads(installed.stdout)["security_incident_response"]["installed"] is True


def test_apps_are_searched_and_inactive_ones_shown_with_all():
    result = run(["snow", "apps", "acme"], FakeInstance(), environ=BASIC)
    assert result.exit_code == 0, result.output
    assert "0 application(s)" in result.stderr
    every = run(["snow", "plugins", "acme", "--all"], FakeInstance(), environ=BASIC)
    assert "x_acme_tools" in every.stdout
    assert "inactive" in every.stdout


def test_no_profile_at_all_says_how_to_set_one_up():
    result = run(["snow", "whoami"], FakeInstance(), environ={})
    assert isinstance(result.exception, ConfigError)
    assert "SNOW_INSTANCE_URL" in (result.exception.hint or "")


def test_sign_in_on_a_basic_profile_says_how_to_use_oauth():
    result = run(["snow", "sign-in"], FakeInstance(), environ=BASIC)
    assert "SNOW_CLIENT_ID" in (result.exception.hint or "")
