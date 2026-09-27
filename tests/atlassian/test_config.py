import pytest

from libre_devops_helpers.atlassian import from_file, profile_from_env, site_url
from libre_devops_helpers.core.config import ConfigFile
from libre_devops_helpers.core.errors import ConfigError


def section(profiles, default=None):
    body = {"profiles": profiles}
    if default:
        body["default_profile"] = default
    return ConfigFile(path=None, data={"atlassian": body})


def test_a_site_is_its_https_address_or_its_name():
    assert site_url("contoso", "x") == "https://contoso.atlassian.net"
    assert site_url("https://Contoso.Atlassian.net/", "x") == "https://contoso.atlassian.net"
    for bad in ("http://contoso.atlassian.net", "https://contoso.atlassian.net/wiki", "ftp://x"):
        with pytest.raises(ConfigError):
            site_url(bad, "x")


def test_profiles_are_read_with_their_token_variable():
    config = from_file(
        section(
            {
                "work": {"site": "contoso", "email": "ana@example.com"},
                "lab": {
                    "site": "https://lab.atlassian.net",
                    "email": "b@example.com",
                    "token_env": "LAB_TOKEN",
                },
            },
            default="work",
        )
    )
    assert config.default_profile == "work"
    assert config.get("work").site == "https://contoso.atlassian.net"
    assert config.get("work").token_env == "JIRA_TOKEN"
    assert config.get("lab").token_env == "LAB_TOKEN"
    with pytest.raises(ConfigError, match="configured: lab, work"):
        config.get("nope")
    assert from_file(ConfigFile(path=None, data={})) is None


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ({"site": "contoso"}, "needs a site and an email"),
        ({"site": "contoso", "email": "not-an-email"}, "not an email address"),
        (
            {"site": "contoso", "email": "a@example.com", "token_env": "1BAD"},
            "environment variable",
        ),
        ({"site": "contoso", "email": "a@example.com", "token": "x"}, "token"),
    ],
    ids=["no-email", "bad-email", "bad-token-env", "token-in-file"],
)
def test_a_profile_that_cannot_be_used_says_why(profile, message):
    with pytest.raises(ConfigError, match=message):
        from_file(section({"work": profile}))


def test_a_default_profile_must_exist():
    with pytest.raises(ConfigError, match="not a configured profile"):
        from_file(section({"work": {"site": "contoso", "email": "a@example.com"}}, default="lab"))


def test_the_environment_makes_the_env_profile():
    env = profile_from_env({"JIRA_INSTANCE": "contoso", "JIRA_EMAIL": "ana@example.com"})
    assert (env.name, env.site, env.email) == (
        "env",
        "https://contoso.atlassian.net",
        "ana@example.com",
    )
    assert profile_from_env({}) is None
    with pytest.raises(ConfigError, match="JIRA_EMAIL is not"):
        profile_from_env({"JIRA_INSTANCE": "contoso"})


def test_the_templates_placeholder_site_is_refused():
    from libre_devops_helpers.atlassian import Profile

    with pytest.raises(ConfigError, match="placeholder"):
        Profile("work", "https://your-site.atlassian.net", "a@example.com").require_real_site()
