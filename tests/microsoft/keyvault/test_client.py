from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.microsoft.clouds import USGOV
from libre_devops_helpers.microsoft.keyvault import KeyVaultClient, expiring, vault_url

NOW = datetime(2026, 9, 24, tzinfo=UTC)

VAULT = "https://kv-app.vault.azure.net"


def epoch(days: int) -> int:
    return int((NOW + timedelta(days=days)).timestamp())


def test_vault_url_accepts_a_name_or_a_url_on_the_cloud_domain():
    assert vault_url("kv-app-prd") == "https://kv-app-prd.vault.azure.net"
    assert vault_url("https://KV-App.vault.azure.net/") == VAULT
    assert vault_url("kv-gov", USGOV) == "https://kv-gov.vault.usgovcloudapi.net"


@pytest.mark.parametrize(
    "value",
    ["kv", "kv_underscore", "https://kv.evil.test", "http://kv.vault.azure.net", "a" * 25],
)
def test_vault_url_refuses_anything_that_could_send_a_token_elsewhere(value):
    with pytest.raises(LdoError):
        vault_url(value)


def test_items_skip_certificate_backing_secrets_and_read_attributes_only():
    replies = {
        "/secrets": {
            "value": [
                {
                    "id": f"{VAULT}/secrets/db-password",
                    "attributes": {"exp": epoch(10), "enabled": True},
                },
                {"id": f"{VAULT}/secrets/tls", "managed": True, "attributes": {}},
            ],
            "nextLink": f"{VAULT}/secrets?page=2",
        },
        "/secrets?page=2": {"value": [{"id": f"{VAULT}/secrets/api-key", "attributes": {}}]},
        "/certificates": {
            "value": [
                {
                    "id": f"{VAULT}/certificates/tls",
                    "attributes": {"exp": epoch(-2)},
                }
            ]
        },
        "/keys": {"value": [{"kid": f"{VAULT}/keys/cmk", "attributes": {"exp": epoch(400)}}]},
    }

    def handler(request):
        parts = urlsplit(request.url)
        key = parts.path + ("?page=2" if "page=2" in parts.query else "")
        return (200, replies[key])

    session, _ = fake_session(handler)
    tokens = StaticTokens()
    client = KeyVaultClient.create(tokens, TENANT, "kv-app", session=session)
    items = client.items()
    assert [(i.kind, i.name) for i in items] == [
        ("secret", "api-key"),
        ("secret", "db-password"),
        ("certificate", "tls"),
        ("key", "cmk"),
    ]
    assert tokens.calls[0] == ("https://vault.azure.net", TENANT)
    soon = expiring(items, timedelta(days=30), now=NOW)
    assert [(i.name, i.days_left(NOW)) for i in soon] == [("tls", -2), ("db-password", 10)]


def test_expiring_leaves_out_disabled_items_unless_asked():
    from libre_devops_helpers.microsoft.keyvault import VaultItem

    item = VaultItem("kv", "secret", "old", False, NOW + timedelta(days=1), None, None, "")
    assert expiring([item], timedelta(days=30), now=NOW) == []
    assert expiring([item], timedelta(days=30), now=NOW, include_disabled=True) == [item]
