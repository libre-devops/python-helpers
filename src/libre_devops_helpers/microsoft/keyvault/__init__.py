"""Key Vault: secret, certificate and key metadata for expiry checks. Never reads values.

Depends only on ``core`` and the shared Microsoft layer. Access rests on Key Vault
data-plane RBAC or access policies, so there are no token scope requirements to declare.
Finding vaults across subscriptions is Resource Graph's job (``azure``); this module
takes vault names. Public API::

    from libre_devops_helpers.microsoft.keyvault import KeyVaultClient, expiring

    with KeyVaultClient.for_profile(profile, tokens, "kv-app-prd") as vault:
        soon = expiring(vault.items(), timedelta(days=30), now=datetime.now(UTC))
"""

from libre_devops_helpers.microsoft.keyvault.client import (
    KINDS,
    ItemKind,
    KeyVaultClient,
    VaultItem,
    expiring,
    vault_url,
)
from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "KINDS",
    "REQUIREMENTS",
    "ItemKind",
    "KeyVaultClient",
    "VaultItem",
    "expiring",
    "vault_url",
]
