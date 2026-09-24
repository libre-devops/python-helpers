"""Microsoft profiles: the ``[microsoft]`` section of the config file.

A profile is a tenant, optionally pinned to one subscription, in one cloud, with one way
of getting tokens. Tenant and subscription ids describe an environment, not code, so
they live in the config file rather than the repository; a client secret never does,
and is read from the environment instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.config import (
    ConfigFile,
    check_name,
    guid,
    https_url,
    load_config_file,
    parse_config_file,
    reject_unknown,
    table,
    text,
)
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.core.token_store import DEFAULT_TOKEN_CACHE, TOKEN_CACHES
from libre_devops_helpers.microsoft.clouds import CLOUDS, PUBLIC, Cloud, get_cloud

SECTION = "microsoft"
PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000"

# How a profile gets tokens. microsoft.auth.credential_for turns each into a credential.
AUTH_METHODS = (
    "azure-cli",
    "interactive",
    "device-code",
    "client-secret",
    "workload-identity",
    "managed-identity",
)
_NEEDS_CLIENT_ID = frozenset({"interactive", "device-code", "client-secret", "workload-identity"})
# The methods whose sign-in comes with a refresh token this tool keeps (token_cache).
DELEGATED_AUTH = frozenset({"interactive", "device-code"})
_SECTION_KEYS = frozenset({"default_profile", "profiles"})
_PROFILE_KEYS = frozenset(
    {
        "description",
        "tenant_id",
        "subscription_id",
        "cloud",
        "mde_url",
        "auth",
        "client_id",
        "workspace_id",
        "token_cache",
    }
)

CONFIG_TEMPLATE = f"""\
# Microsoft profiles. Each is a tenant, optionally pinned to a subscription.
# Replace the placeholder ids, then run: {brand.COMMAND} profiles
[microsoft]
# Used when neither --profile nor {brand.PROFILE_ENV} is given.
default_profile = "prod-tenant"

[microsoft.profiles.prod]
description = "Production subscription"
tenant_id = "{PLACEHOLDER_ID}"
subscription_id = "{PLACEHOLDER_ID}"

[microsoft.profiles.dev]
description = "Development subscription"
tenant_id = "{PLACEHOLDER_ID}"
subscription_id = "{PLACEHOLDER_ID}"

[microsoft.profiles.prod-tenant]
description = "Production tenant"
tenant_id = "{PLACEHOLDER_ID}"

[microsoft.profiles.test-tenant]
description = "Test tenant"
tenant_id = "{PLACEHOLDER_ID}"
# A regional Defender endpoint can be set per profile:
# mde_url = "https://api-eu.securitycenter.microsoft.com"

# Other optional profile keys:
#
# cloud = "public"          public (the default), usgov or china; match it with 'az cloud set'
# workspace_id = "<guid>"   the Log Analytics workspace 'logs query' uses by default
#
# auth picks how the profile gets tokens. The default is your Azure CLI sign-in.
# auth = "interactive"         needs client_id of your own public client app; signs you in
#                              in a browser, for delegated scopes the Azure CLI lacks (PIM)
# auth = "device-code"         the same, with a code to enter, for SSH, WSL and headless use
# auth = "client-secret"       needs client_id; the secret is read from AZURE_CLIENT_SECRET
# auth = "workload-identity"   needs client_id; the federated token is read from
#                              AZURE_FEDERATED_TOKEN_FILE, or requested from GitHub Actions
# auth = "managed-identity"    client_id is optional and picks a user-assigned identity
# client_id = "<app or identity client id>"
#
# For interactive and device-code, token_cache says where the sign-in is kept between
# commands, so you are not asked to sign in for each one:
# token_cache = "file"         the default: a plaintext file only your account can read
#                              (0600), which works headless
# token_cache = "keychain"     the operating system's keychain (needs the keychain extra
#                              on macOS and Linux; DPAPI encryption on Windows)
# token_cache = "memory"       nowhere; each command signs in afresh
"""


@dataclass(frozen=True)
class Profile:
    """One Azure context: a tenant, optionally pinned to a subscription."""

    name: str
    tenant_id: str
    subscription_id: str | None = None
    description: str = ""
    cloud: Cloud = PUBLIC
    # A regional Defender endpoint; the token is still for the cloud's Defender resource.
    mde_url: str | None = None
    auth: str = "azure-cli"
    client_id: str | None = None
    workspace_id: str | None = None
    # Where an interactive or device-code sign-in is kept between commands.
    token_cache: str = DEFAULT_TOKEN_CACHE

    @property
    def kind(self) -> str:
        """``subscription`` when pinned to a subscription, otherwise ``tenant``."""
        return "subscription" if self.subscription_id else "tenant"

    @property
    def has_placeholder_ids(self) -> bool:
        """True while the profile still carries the template's all-zero ids."""
        return PLACEHOLDER_ID in (self.tenant_id, self.subscription_id)

    def require_real_ids(self) -> None:
        """Raise ConfigError while the profile still carries placeholder ids."""
        if self.has_placeholder_ids:
            raise ConfigError(
                f"profile {self.name!r} still has placeholder ids",
                hint="set its tenant_id (and subscription_id) in the config file",
            )


@dataclass(frozen=True)
class MicrosoftConfig:
    """The parsed ``[microsoft]`` section."""

    path: Path
    profiles: Mapping[str, Profile]
    default_profile: str | None = None

    def get(self, name: str) -> Profile:
        """The named profile. Raises ConfigError listing the known names when absent."""
        try:
            return self.profiles[name]
        except KeyError:
            known = ", ".join(sorted(self.profiles)) or "none"
            raise ConfigError(
                f"unknown Microsoft profile {name!r} (configured: {known})",
                hint=f"edit {self.path}",
            ) from None


def load_config(path: Path | None = None) -> MicrosoftConfig:
    """Read the config file and parse its ``[microsoft]`` section."""
    return from_file(load_config_file(path))


def parse_config(data: Mapping[str, Any], path: Path) -> MicrosoftConfig:
    """Parse already-loaded TOML (the whole file) for its ``[microsoft]`` section."""
    return from_file(parse_config_file(data, path))


def from_file(file: ConfigFile) -> MicrosoftConfig:
    """Validate the ``[microsoft]`` section. Unknown keys are errors, so typos surface."""
    where = f"{file.path}: [{SECTION}]"
    section = file.section(SECTION)
    if section is None:
        raise ConfigError(
            f"{file.path} has no [{SECTION}] section",
            hint=f"add [microsoft.profiles.<name>] tables; {brand.command('config init')} "
            "writes a template",
        )
    reject_unknown(section, _SECTION_KEYS, where)
    tables = section.get("profiles")
    if not isinstance(tables, dict) or not tables:
        raise ConfigError(f"{where}: define at least one [microsoft.profiles.<name>] table")
    profiles = {
        str(name): _parse_profile(str(name), value, str(file.path))
        for name, value in tables.items()
    }
    default = section.get("default_profile")
    if default is not None and (not isinstance(default, str) or default not in profiles):
        raise ConfigError(f"{where}: default_profile {default!r} is not a configured profile")
    return MicrosoftConfig(path=file.path, profiles=profiles, default_profile=default)


def _parse_profile(name: str, value: object, path: str) -> Profile:
    where = f"{path}: [microsoft.profiles.{name}]"
    check_name(name, where)
    data = table(value, where)
    reject_unknown(data, _PROFILE_KEYS, where)

    tenant_id = guid(data, "tenant_id", where)
    if tenant_id is None:
        raise ConfigError(f"{where}: tenant_id is required")

    cloud_name = text(data, "cloud", where)
    if cloud_name is not None and cloud_name.lower() not in CLOUDS:
        raise ConfigError(f"{where}: cloud must be one of {', '.join(CLOUDS)}")

    auth = text(data, "auth", where) or "azure-cli"
    if auth not in AUTH_METHODS:
        raise ConfigError(f"{where}: auth must be one of {', '.join(AUTH_METHODS)}")
    client_id = guid(data, "client_id", where)
    if auth in _NEEDS_CLIENT_ID and client_id is None:
        raise ConfigError(f"{where}: auth = {auth!r} needs a client_id")
    token_cache = text(data, "token_cache", where)
    if token_cache is not None and token_cache not in TOKEN_CACHES:
        raise ConfigError(f"{where}: token_cache must be one of {', '.join(TOKEN_CACHES)}")
    if token_cache is not None and auth not in DELEGATED_AUTH:
        raise ConfigError(
            f'{where}: token_cache applies to auth = "interactive" or "device-code"',
            hint="the Azure CLI keeps its own sign-in, and the other methods have none to keep",
        )

    return Profile(
        name=name,
        tenant_id=tenant_id,
        subscription_id=guid(data, "subscription_id", where),
        description=text(data, "description", where) or "",
        cloud=get_cloud(cloud_name) if cloud_name else PUBLIC,
        mde_url=https_url(data, "mde_url", where),
        auth=auth,
        client_id=client_id,
        workspace_id=guid(data, "workspace_id", where),
        token_cache=token_cache or DEFAULT_TOKEN_CACHE,
    )
