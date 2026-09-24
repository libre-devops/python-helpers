"""Key Vault secret, certificate and key metadata, for expiry checks.

Only list operations are used, and they return attributes (dates, enabled, content
type) but never a secret value. Reading them needs a data-plane role such as Key Vault
Reader, or a list permission in an access policy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.microsoft.clouds import PUBLIC, Cloud
from libre_devops_helpers.microsoft.config import Profile

API_VERSION = "7.4"
_VAULT_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$")

ItemKind = Literal["secret", "certificate", "key"]
KINDS: tuple[ItemKind, ...] = ("secret", "certificate", "key")


def vault_url(vault: str, cloud: Cloud = PUBLIC) -> str:
    """The data-plane URL for a vault given by name or by URL, checked against the cloud.

    A URL must be on the cloud's Key Vault domain, so a token is never sent elsewhere.
    """
    value = vault.strip()
    if "://" in value:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host.endswith("." + cloud.keyvault_suffix):
            raise LdoError(
                f"{vault!r} is not a Key Vault URL in the {cloud.name} cloud",
                hint=f"expected https://<name>.{cloud.keyvault_suffix}",
            )
        return f"https://{host}"
    if not _VAULT_NAME.match(value):
        raise LdoError(f"not a Key Vault name: {vault!r}")
    return f"https://{value.lower()}.{cloud.keyvault_suffix}"


@dataclass(frozen=True)
class VaultItem:
    """One secret, certificate or key, by its attributes. Never holds a value."""

    vault: str
    kind: ItemKind
    name: str
    enabled: bool | None
    expires: datetime | None
    not_before: datetime | None
    updated: datetime | None
    content_type: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def days_left(self, now: datetime) -> int | None:
        """Whole days until expiry (negative once expired), or None with no expiry set."""
        return None if self.expires is None else (self.expires - now).days

    @classmethod
    def from_json(cls, vault: str, kind: ItemKind, data: Mapping[str, Any]) -> VaultItem:
        attributes = data.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        identifier = str(data.get("kid") or data.get("id") or "")
        enabled = attributes.get("enabled")
        return cls(
            vault=vault,
            kind=kind,
            name=identifier.rstrip("/").rsplit("/", 1)[-1],
            enabled=enabled if isinstance(enabled, bool) else None,
            expires=_epoch(attributes.get("exp")),
            not_before=_epoch(attributes.get("nbf")),
            updated=_epoch(attributes.get("updated")),
            content_type=str(data.get("contentType") or ""),
            raw=dict(data),
        )


class KeyVaultClient:
    """Metadata listing for one vault. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient, vault: str) -> None:
        self.api = api
        self.vault = vault

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        vault: str,
        *,
        cloud: Cloud = PUBLIC,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> KeyVaultClient:
        """A client for one vault (a name or URL) in ``tenant_id``."""
        url = vault_url(vault, cloud)
        api = ApiClient(
            url,
            token_source(tokens, f"https://{cloud.keyvault_suffix}", tenant_id),
            name=f"Key Vault {urlsplit(url).hostname}",
            verify=verify,
            session=session,
        )
        return cls(api, (urlsplit(url).hostname or "").split(".", 1)[0])

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        vault: str,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> KeyVaultClient:
        """A client for one vault in a configured profile's tenant and cloud."""
        return cls.create(
            tokens, profile.tenant_id, vault, cloud=profile.cloud, verify=verify, session=session
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def items(self, kinds: Iterable[ItemKind] = KINDS) -> list[VaultItem]:
        """Secrets, certificates and keys in the vault, by kind then name.

        A certificate's backing secret and key are ``managed`` and left out, so each
        certificate is listed once.
        """
        found: list[VaultItem] = []
        for kind in kinds:
            for item in self.api.get_all(
                f"/{kind}s", params={"api-version": API_VERSION}, next_link="nextLink"
            ):
                if item.get("managed") is True:
                    continue
                found.append(VaultItem.from_json(self.vault, kind, item))
        return sorted(found, key=lambda item: (KINDS.index(item.kind), item.name.casefold()))


def expiring(
    items: Iterable[VaultItem],
    within: timedelta,
    *,
    now: datetime,
    include_expired: bool = True,
    include_disabled: bool = False,
) -> list[VaultItem]:
    """Items that expire within ``within`` of ``now`` (and expired ones), soonest first.

    Disabled items are left out unless asked for: nothing can use them anyway.
    """
    selected = [
        item
        for item in items
        if item.expires is not None
        and item.expires - now <= within
        and (include_expired or item.expires >= now)
        and (include_disabled or item.enabled is not False)
    ]
    return sorted(selected, key=lambda item: item.expires or now)


def _epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, UTC)
