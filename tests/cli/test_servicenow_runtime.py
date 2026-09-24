import pytest

from fakes.servicenow import CLIENT_ID, INSTANCE
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core.errors import ConfigError

ENV = {"SNOW_INSTANCE_URL": INSTANCE, "SNOW_INSTANCE_USERNAME": "ana"}


def runtime(tmp_path, body: str | None = None, environ=None) -> Runtime:
    path = tmp_path / "config.toml"
    if body is not None:
        path.write_text(body, encoding="utf-8")
    return Runtime(config_path=path, environ=environ or {})


TWO = f"""
[servicenow.profiles.dev]
instance = "{INSTANCE}"
client_id = "{CLIENT_ID}"

[servicenow.profiles.work]
instance = "https://itsm.example.com"
client_id = "{CLIENT_ID}"
"""


def test_a_named_profile_wins_then_the_default_then_the_environment(tmp_path):
    snow = runtime(tmp_path, TWO + '\n[servicenow]\ndefault_profile = "work"\n', ENV).servicenow
    assert snow.profile("dev").name == "dev"
    assert snow.profile(None).name == "work"
    assert snow.profile("env").instance == INSTANCE
    assert [profile.name for profile in snow.profiles()] == ["dev", "work", "env"]


def test_without_a_default_the_environment_is_used_then_a_lone_profile(tmp_path):
    assert runtime(tmp_path, TWO, ENV).servicenow.profile(None).name == "env"
    lone = f'[servicenow.profiles.dev]\ninstance = "{INSTANCE}"\n'
    assert runtime(tmp_path, lone).servicenow.profile(None).name == "dev"
    with pytest.raises(ConfigError, match="no ServiceNow profile selected"):
        runtime(tmp_path, TWO).servicenow.profile(None)


def test_an_unknown_profile_lists_the_known_ones(tmp_path):
    with pytest.raises(ConfigError, match=r"configured: dev, work"):
        runtime(tmp_path, TWO).servicenow.profile("prod")
    with pytest.raises(ConfigError, match="unknown ServiceNow profile 'prod'") as caught:
        runtime(tmp_path / "no-config").servicenow.profile("prod")
    assert "SNOW_INSTANCE_URL" in (caught.value.hint or "")


def test_the_templates_placeholder_instance_is_refused(tmp_path):
    body = '[servicenow.profiles.dev]\ninstance = "https://dev00000.service-now.com"\n'
    with pytest.raises(ConfigError, match="placeholder"):
        runtime(tmp_path, body).servicenow.profile("dev")
