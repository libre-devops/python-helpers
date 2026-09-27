"""The ``[atlassian]`` config section: Atlassian Cloud sites, for Jira and Confluence.

Each profile is one site and the account on it. Jira and Confluence share a site, and
both read with the account's API token, sent with its email as HTTP Basic: the token
reads whatever that account can, and nothing more. The token never goes in the file: it
comes from an environment variable (``JIRA_TOKEN`` unless a profile names another).
Without an ``[atlassian]`` section, ``JIRA_INSTANCE``, ``JIRA_EMAIL`` and ``JIRA_TOKEN``
make a profile called ``env``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.config import (
    ConfigFile,
    check_name,
    load_config_file,
    reject_unknown,
    table,
    text,
)
from libre_devops_helpers.core.errors import ConfigError

SECTION = "atlassian"
ENV_PROFILE = "env"
SITE_ENV = "JIRA_INSTANCE"
EMAIL_ENV = "JIRA_EMAIL"
TOKEN_ENV = "JIRA_TOKEN"
PLACEHOLDER_SITE = "https://your-site.atlassian.net"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SITE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SECTION_KEYS = frozenset({"default_profile", "profiles"})
_PROFILE_KEYS = frozenset({"description", "site", "email", "token_env"})

CONFIG_TEMPLATE = f"""\
# Atlassian Cloud sites, for Jira and Confluence. Each profile is a site and the account
# you read it as, with an API token (https://id.atlassian.com/manage-profile/security/
# api-tokens) from the environment, never this file. Without this section, {SITE_ENV},
# {EMAIL_ENV} and {TOKEN_ENV} make a profile called "{ENV_PROFILE}".
# Replace the placeholder site, then run: {brand.COMMAND} jira whoami
[atlassian]
default_profile = "work"

[atlassian.profiles.work]
description = "Our Atlassian site"
site = "{PLACEHOLDER_SITE}"
email = "you@example.com"
# token_env = "{TOKEN_ENV}"   another variable, for a second site
"""


@dataclass(frozen=True)
class Profile:
    """One Atlassian Cloud site, and the account to read it as."""

    name: str
    site: str
    email: str
    token_env: str = TOKEN_ENV
    description: str = ""

    @property
    def host(self) -> str:
        """The site's host name, from its URL."""
        return urlsplit(self.site).netloc

    def require_real_site(self) -> None:
        """A ConfigError when the site is still the template's placeholder."""
        if self.site == PLACEHOLDER_SITE:
            raise ConfigError(
                f"Atlassian profile {self.name!r} still has the template's placeholder site",
                hint="set its site in the config file",
            )


@dataclass(frozen=True)
class AtlassianConfig:
    """The parsed ``[atlassian]`` section."""

    path: Path | None
    profiles: Mapping[str, Profile]
    default_profile: str | None = None

    def get(self, name: str) -> Profile:
        """The profile called ``name``, or a ConfigError listing those there are."""
        try:
            return self.profiles[name]
        except KeyError:
            known = ", ".join(sorted(self.profiles)) or "none"
            raise ConfigError(
                f"unknown Atlassian profile {name!r} (configured: {known})",
                hint=f"edit {self.path}" if self.path else None,
            ) from None


def site_url(value: str, where: str) -> str:
    """``https://<name>.atlassian.net``, or another https URL, without a trailing slash.

    A bare site name (``contoso``) means ``https://contoso.atlassian.net``.
    """
    value = value.strip()
    if _SITE_NAME.fullmatch(value):
        return f"https://{value}.atlassian.net"
    parts = urlsplit(value)
    # The token goes with every request, so plain http is never acceptable.
    if parts.scheme != "https" or not parts.netloc:
        raise ConfigError(f"{where}: site must be an https:// URL or a site name")
    if parts.path.strip("/") or parts.query or parts.fragment:
        raise ConfigError(f"{where}: site must be the site's address, with no path")
    return f"https://{parts.netloc.lower()}"


def load_config(path: Path | None = None) -> AtlassianConfig | None:
    """Read the config file's ``[atlassian]`` section, or None when it has none."""
    return from_file(load_config_file(path))


def from_file(file: ConfigFile) -> AtlassianConfig | None:
    """Validate the ``[atlassian]`` section; None when the file has none."""
    section = file.section(SECTION)
    if section is None:
        return None
    where = f"{file.path}: [{SECTION}]"
    reject_unknown(section, _SECTION_KEYS, where)
    profiles = {
        name: _parse_profile(name, value, str(file.path))
        for name, value in table(section.get("profiles", {}), f"{where}.profiles").items()
    }
    default = text(section, "default_profile", where)
    if default is not None and default not in profiles:
        raise ConfigError(f"{where}: default_profile {default!r} is not a configured profile")
    return AtlassianConfig(path=file.path, profiles=profiles, default_profile=default)


def profile_from_env(environ: Mapping[str, str] = os.environ) -> Profile | None:
    """The ``env`` profile from ``JIRA_INSTANCE`` and ``JIRA_EMAIL``, or None without a site."""
    site = environ.get(SITE_ENV, "").strip()
    if not site:
        return None
    email = environ.get(EMAIL_ENV, "").strip()
    if not email:
        raise ConfigError(
            f"{SITE_ENV} is set but {EMAIL_ENV} is not",
            hint=f"set {EMAIL_ENV} to the Atlassian account's email, which goes with its token",
        )
    return Profile(
        name=ENV_PROFILE,
        site=site_url(site, SITE_ENV),
        email=_email(email, EMAIL_ENV),
        description="from the environment",
    )


def _parse_profile(name: str, value: Any, path: str) -> Profile:
    where = f"{path}: [{SECTION}.profiles.{name}]"
    check_name(name, where)
    body = table(value, where)
    reject_unknown(body, _PROFILE_KEYS, where)
    site = text(body, "site", where)
    email = text(body, "email", where)
    if not site or not email:
        raise ConfigError(f"{where}: needs a site and an email")
    token_env = text(body, "token_env", where) or TOKEN_ENV
    if not _ENV_NAME.fullmatch(token_env):
        raise ConfigError(f"{where}: token_env must be an environment variable's name")
    return Profile(
        name=name,
        site=site_url(site, where),
        email=_email(email, where),
        token_env=token_env,
        description=text(body, "description", where) or "",
    )


def _email(value: str, where: str) -> str:
    if not _EMAIL.fullmatch(value.strip()):
        raise ConfigError(f"{where}: {value!r} is not an email address")
    return value.strip()
