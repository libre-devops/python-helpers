import sys
from pathlib import Path

import pytest

from libre_devops_helpers.core.config import (
    default_config_path,
    load_config_file,
    parse_config_file,
)
from libre_devops_helpers.core.errors import ConfigError, ConfigNotFoundError

PATH = Path("config.toml")


def test_known_sections_and_ca_bundle_are_accepted():
    file = parse_config_file(
        {"ca_bundle": "~/certs/ca.pem", "microsoft": {"profiles": {}}},
        PATH,
        sections=["microsoft"],
    )
    assert file.ca_bundle is not None
    assert file.ca_bundle.name == "ca.pem"
    assert file.section("microsoft") == {"profiles": {}}
    assert file.section("servicenow") is None


def test_an_unknown_top_level_key_is_a_typo_when_sections_are_known():
    with pytest.raises(ConfigError, match="unknown key"):
        parse_config_file({"microsfot": {}}, PATH, sections=["microsoft"])
    # A library caller that only knows its own vendor skips the check.
    assert parse_config_file({"microsfot": {}}, PATH).section("microsfot") == {}


def test_a_section_must_be_a_table():
    with pytest.raises(ConfigError, match="must be a table"):
        parse_config_file({"microsoft": "yes"}, PATH).section("microsoft")


def test_load_reports_a_missing_file_and_bad_toml(tmp_path):
    with pytest.raises(ConfigNotFoundError) as caught:
        load_config_file(tmp_path / "absent.toml")
    assert "ldo config init" in (caught.value.hint or "")
    bad = tmp_path / "bad.toml"
    bad.write_text("[microsoft\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config_file(bad)


def test_default_config_path_prefers_the_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("LDO_CONFIG", str(tmp_path / "custom.toml"))
    assert default_config_path() == tmp_path / "custom.toml"


@pytest.mark.skipif(sys.platform == "win32", reason="XDG applies to Linux and macOS")
def test_default_config_path_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.delenv("LDO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "ldo" / "config.toml"


def test_the_network_settings_are_read_from_the_top_level(tmp_path):
    file = parse_config_file(
        {"proxy": "127.0.0.1:3129", "no_proxy": ".corp.example, localhost", "ca_bundle": "c.pem"},
        tmp_path / "config.toml",
        sections=["microsoft"],
    )
    settings = file.network_settings()
    assert settings.proxy == "http://127.0.0.1:3129"
    assert settings.no_proxy == (".corp.example", "localhost")
    assert settings.ca_bundle is not None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"proxy": 3128}, "proxy must be a string"),
        ({"proxy": "socks5://x:1"}, "is not a proxy address"),
        ({"no_proxy": 7}, "comma-separated string or a list"),
    ],
)
def test_bad_network_settings_are_refused(tmp_path, data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config_file(data, tmp_path / "config.toml", sections=["microsoft"])
