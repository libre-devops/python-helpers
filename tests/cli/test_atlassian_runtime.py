import pytest

from fakes.atlassian import ENV
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core.errors import ConfigError

SECTION = """
[atlassian]
default_profile = "work"

[atlassian.profiles.work]
site = "contoso"
email = "ana@example.com"

[atlassian.profiles.lab]
site = "lab"
email = "ben@example.com"
token_env = "LAB_TOKEN"
"""


def runtime(tmp_path, text="", environ=None):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return Runtime(config_path=path, environ=environ or {}).atlassian


def test_the_named_profile_else_the_default_else_the_environment(tmp_path):
    configured = runtime(tmp_path, SECTION, ENV)
    assert configured.profile(None).name == "work"
    assert configured.profile("lab").token_env == "LAB_TOKEN"
    assert configured.profile("env").site == "https://contoso.atlassian.net"
    assert [p.name for p in configured.profiles()] == ["work", "lab", "env"]
    with pytest.raises(ConfigError, match="configured: lab, work"):
        configured.profile("nope")
    assert runtime(tmp_path, "", ENV).profile(None).name == "env"


def test_one_profile_needs_no_default_and_none_is_an_error_saying_how(tmp_path):
    one = SECTION.replace('default_profile = "work"\n', "").split("[atlassian.profiles.lab]")[0]
    assert runtime(tmp_path, one).profile(None).name == "work"
    with pytest.raises(ConfigError, match="no Atlassian profile selected") as error:
        runtime(tmp_path).profile(None)
    assert "JIRA_INSTANCE" in error.value.hint
    with pytest.raises(ConfigError, match="unknown Atlassian profile"):
        runtime(tmp_path).profile("work")


def test_without_a_config_file_the_environment_still_works(tmp_path):
    lone = Runtime(config_path=tmp_path / "missing.toml", environ=ENV).atlassian
    assert lone.profile(None).name == "env"
    assert lone.config() is None
