import pytest

from libre_devops_helpers.core.errors import ConfigError, LdoError
from libre_devops_helpers.microsoft.clouds import CHINA, PUBLIC, USGOV, get_cloud
from libre_devops_helpers.microsoft.resources import (
    GRAPH_APP_ID,
    resolve_resource,
    resources_for,
)


def test_every_cloud_endpoint_is_https_except_the_keyvault_suffix():
    for cloud in (PUBLIC, USGOV, CHINA):
        for url in (cloud.login_url, cloud.graph_url, cloud.arm_url, cloud.log_analytics_url):
            assert url.startswith("https://"), (cloud.name, url)
        assert "://" not in cloud.keyvault_suffix


def test_get_cloud_is_case_insensitive_and_rejects_unknown_names():
    assert get_cloud("USGov") is USGOV
    with pytest.raises(ConfigError, match="unknown cloud"):
        get_cloud("mars")


def test_defender_is_absent_where_the_cloud_has_none():
    assert "mde" not in resources_for(CHINA)
    with pytest.raises(ConfigError, match="not available"):
        CHINA.require_mde()


def test_resources_accept_their_url_or_app_id_as_audience():
    graph = resources_for(USGOV)["graph"]
    assert graph.url == "https://graph.microsoft.us"
    assert {"https://graph.microsoft.us", GRAPH_APP_ID} <= graph.audiences
    arm = resources_for(PUBLIC)["arm"]
    assert arm.url == "https://management.azure.com/"
    assert "https://management.core.windows.net" in arm.audiences


def test_resolve_resource_by_key_url_or_ad_hoc():
    assert resolve_resource("GRAPH").key == "graph"
    assert resolve_resource("https://graph.microsoft.us/", USGOV).key == "graph"
    assert resolve_resource("https://vault.azure.net").key == "keyvault"
    custom = resolve_resource("https://api.example.test")
    assert custom.key == "https://api.example.test"
    with pytest.raises(LdoError, match="unknown resource"):
        resolve_resource("nope")
