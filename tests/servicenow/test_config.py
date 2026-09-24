from pathlib import Path

import pytest

from libre_devops_helpers.core.config import parse_config_file
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.servicenow.config import (
    CONFIG_TEMPLATE,
    DEFAULT_REDIRECT_URI,
    from_file,
    instance_url,
    profile_from_env,
)

PATH = Path("config.toml")


def parse(**profile):
    data = {"servicenow": {"profiles": {"dev": {"instance": "dev12345", **profile}}}}
    return from_file(parse_config_file(data, PATH))


def test_a_profile_defaults_to_oauth_in_a_browser_with_a_kept_sign_in():
    dev = parse(client_id="abc").profiles["dev"]
    assert dev.instance == "https://dev12345.service-now.com"
    assert (dev.auth, dev.sign_in, dev.token_cache) == ("oauth", "browser", "file")
    assert dev.redirect_uri == DEFAULT_REDIRECT_URI
    assert (dev.password_env, dev.client_secret_env) == (
        "SNOW_INSTANCE_PASSWORD",
        "SNOW_CLIENT_SECRET",
    )


def test_every_key_is_read():
    dev = parse(
        username="ana",
        auth="oauth",
        sign_in="password",
        client_id="abc",
        redirect_uri="https://tools.example.com/callback",
        token_cache="keychain",
        password_env="WORK_SNOW_PASSWORD",
        client_secret_env="WORK_SNOW_SECRET",
        description="work",
    ).profiles["dev"]
    assert (dev.username, dev.sign_in, dev.token_cache) == ("ana", "password", "keychain")
    assert dev.redirect_uri == "https://tools.example.com/callback"
    assert (dev.password_env, dev.client_secret_env) == ("WORK_SNOW_PASSWORD", "WORK_SNOW_SECRET")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("dev12345", "https://dev12345.service-now.com"),
        ("https://Dev12345.service-now.com/", "https://dev12345.service-now.com"),
        ("https://itsm.example.com", "https://itsm.example.com"),
    ],
)
def test_instance_addresses_are_normalised(value, expected):
    assert instance_url(value, "here") == expected


@pytest.mark.parametrize(
    "value",
    ["http://dev12345.service-now.com", "https://dev12345.service-now.com/now/nav", "ftp://x"],
)
def test_an_instance_must_be_an_https_address_without_a_path(value):
    with pytest.raises(ConfigError, match="instance must be"):
        instance_url(value, "here")


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ({"auth": "saml"}, "auth must be one of oauth, basic"),
        ({"sign_in": "magic"}, "sign_in must be one of browser, password"),
        ({"redirect_uri": "http://example.com/cb"}, "redirect_uri must be"),
        ({"auth": "basic", "sign_in": "browser"}, 'apply to auth = "oauth"'),
        ({"auth": "basic", "token_cache": "file"}, 'token_cache applies to auth = "oauth"'),
        ({"token_cache": "disk"}, "token_cache must be one of"),
        ({"password_env": "not a name"}, "must be an environment variable name"),
        ({"colour": "blue"}, "unknown key"),
    ],
)
def test_bad_profiles_are_refused(profile, message):
    with pytest.raises(ConfigError, match=message):
        parse(**profile)


def test_an_instance_is_required_and_default_profile_must_exist():
    with pytest.raises(ConfigError, match="instance is required"):
        from_file(parse_config_file({"servicenow": {"profiles": {"dev": {}}}}, PATH))
    data = {"servicenow": {"default_profile": "prod", "profiles": {"dev": {"instance": "d1"}}}}
    with pytest.raises(ConfigError, match="default_profile 'prod'"):
        from_file(parse_config_file(data, PATH))


def test_a_file_without_the_section_has_no_servicenow_config():
    assert from_file(parse_config_file({}, PATH)) is None


def test_the_environment_makes_a_profile():
    assert profile_from_env({}) is None
    basic = profile_from_env(
        {"SNOW_INSTANCE_URL": "https://dev1.service-now.com", "SNOW_INSTANCE_USERNAME": "admin"}
    )
    assert (basic.name, basic.auth, basic.username) == ("env", "basic", "admin")
    oauth = profile_from_env(
        {"SNOW_INSTANCE_URL": "dev1", "SNOW_CLIENT_ID": "abc", "SNOW_INSTANCE_PASSWORD": "x"}
    )
    assert (oauth.auth, oauth.sign_in) == ("oauth", "password")
    browser = profile_from_env({"SNOW_INSTANCE_URL": "dev1", "SNOW_CLIENT_ID": "abc"})
    assert browser.sign_in == "browser"


def test_the_template_parses_and_its_placeholder_is_refused():
    import tomllib

    config = from_file(parse_config_file(tomllib.loads(CONFIG_TEMPLATE), PATH))
    dev = config.get("dev")
    assert dev.has_placeholder
    with pytest.raises(ConfigError, match="placeholder"):
        dev.require_real_instance()
    with pytest.raises(ConfigError, match="unknown ServiceNow profile 'prod'"):
        config.get("prod")
