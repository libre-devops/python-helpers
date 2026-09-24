import tomllib
from pathlib import Path

import pytest

from fakes import SUBSCRIPTION, TENANT
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.microsoft.config import CONFIG_TEMPLATE, load_config, parse_config

PATH = Path("config.toml")
CLIENT_ID = "77777777-7777-7777-7777-777777777777"


def config(**profile: object) -> dict[str, object]:
    return {"microsoft": {"profiles": {"prod": {"tenant_id": TENANT, **profile}}}}


def test_template_parses_with_the_four_profiles_all_placeholders():
    parsed = parse_config(tomllib.loads(CONFIG_TEMPLATE), PATH)
    assert list(parsed.profiles) == ["prod", "dev", "prod-tenant", "test-tenant"]
    assert parsed.default_profile == "prod-tenant"
    assert all(profile.has_placeholder_ids for profile in parsed.profiles.values())
    with pytest.raises(ConfigError, match="placeholder"):
        parsed.get("test-tenant").require_real_ids()


def test_profile_ids_are_normalised_and_kind_follows_subscription():
    parsed = parse_config(config(subscription_id=SUBSCRIPTION.upper()), PATH)
    prod = parsed.get("prod")
    assert prod.subscription_id == SUBSCRIPTION
    assert prod.kind == "subscription"
    assert parse_config(config(), PATH).get("prod").kind == "tenant"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (config(tenant="typo"), "unknown key"),
        ({"microsoft": {"defaults": "x", "profiles": {}}}, "unknown key"),
        (config(subscription_id="not-a-guid"), "must be a GUID"),
        ({"microsoft": {"profiles": {"prod": {}}}}, "tenant_id is required"),
        (
            {"microsoft": {"default_profile": "missing", **config()["microsoft"]}},
            "default_profile",
        ),
        (config(mde_url="http://api.securitycenter.microsoft.com"), "https"),
        (config(graph_url="https://graph.microsoft.com"), "unknown key"),
        (config(cloud="mars"), "cloud must be one of"),
        (config(auth="password"), "auth must be one of"),
        (config(auth="client-secret"), "needs a client_id"),
        (config(workspace_id="law-prd"), "must be a GUID"),
        ({"microsoft": {"profiles": {"Prod": {"tenant_id": TENANT}}}}, "lowercase"),
        ({"microsoft": {"profiles": {}}}, "at least one"),
        ({"ca_bundle": "x"}, r"no \[microsoft\] section"),
    ],
)
def test_invalid_config_is_rejected(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data, PATH)


def test_cloud_auth_and_workspace_are_read():
    parsed = parse_config(
        config(cloud="USGov", auth="client-secret", client_id=CLIENT_ID, workspace_id=TENANT),
        PATH,
    )
    prod = parsed.get("prod")
    assert prod.cloud.name == "usgov"
    assert prod.cloud.graph_url == "https://graph.microsoft.us"
    assert (prod.auth, prod.client_id, prod.workspace_id) == ("client-secret", CLIENT_ID, TENANT)


def test_defaults_are_the_public_cloud_and_the_azure_cli():
    prod = parse_config(config(), PATH).get("prod")
    assert (prod.cloud.name, prod.auth, prod.mde_url) == ("public", "azure-cli", None)


def test_unknown_profile_lists_the_known_ones():
    with pytest.raises(ConfigError, match=r"configured: prod"):
        parse_config(config(), PATH).get("nope")


def test_load_config_reads_the_microsoft_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f'[microsoft.profiles.test-tenant]\ntenant_id = "{TENANT}"\n', encoding="utf-8")
    assert load_config(path).get("test-tenant").tenant_id == TENANT
