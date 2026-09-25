"""The ``[servicenow]`` config section: named instances, and how to sign in to each.

Each profile is one instance and one account on it. Sign-in is OAuth by default, through
an OAuth application registry entry on the instance: in a browser (single sign-on and
MFA included, and headless too, by pasting back the address the browser lands on), or
with a password once. Either way the refresh token is kept, so later commands sign in by
themselves. ``basic`` (the password with every request) is there for instances that allow
it.

Passwords and client secrets never go in the file. They come from environment variables
(``SNOW_INSTANCE_PASSWORD`` and ``SNOW_CLIENT_SECRET`` unless a profile names others), or
are asked for, hidden, when you sign in. Without a ``[servicenow]`` section,
``SNOW_INSTANCE_URL`` makes a profile called ``env``.
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
from libre_devops_helpers.core.token_store import DEFAULT_TOKEN_CACHE, TOKEN_CACHES

SECTION = "servicenow"
ENV_PROFILE = "env"
URL_ENV = "SNOW_INSTANCE_URL"
USERNAME_ENV = "SNOW_INSTANCE_USERNAME"
PASSWORD_ENV = "SNOW_INSTANCE_PASSWORD"
CLIENT_ID_ENV = "SNOW_CLIENT_ID"
CLIENT_SECRET_ENV = "SNOW_CLIENT_SECRET"
PLACEHOLDER_HOST = "dev00000.service-now.com"
# Where the browser is sent after an OAuth sign-in: set it as the application registry
# entry's Redirect URL. Nothing needs to listen there; you paste the address back.
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"

# oauth: a token and a kept refresh token, through an OAuth application registry entry.
# basic: the username and password with every request.
AUTH_METHODS = ("oauth", "basic")
# How an oauth profile signs in when it has no kept refresh token.
SIGN_INS = ("browser", "password")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INSTANCE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_SECTION_KEYS = frozenset({"default_profile", "profiles"})
_PROFILE_KEYS = frozenset(
    {
        "description",
        "instance",
        "username",
        "auth",
        "client_id",
        "sign_in",
        "redirect_uri",
        "token_cache",
        "password_env",
        "client_secret_env",
    }
)

CONFIG_TEMPLATE = f"""\
# ServiceNow instances. Each profile is an instance and the account you sign in with.
# Passwords and client secrets come from the environment, never this file. Without
# this section, {URL_ENV} and {USERNAME_ENV} make a profile called "{ENV_PROFILE}".
# Replace the placeholder instance, then run: {brand.COMMAND} snow whoami
[servicenow]
default_profile = "dev"

[servicenow.profiles.dev]
description = "Personal developer instance"
instance = "https://{PLACEHOLDER_HOST}"
# The OAuth application registry entry's client id (or {CLIENT_ID_ENV}). Its secret comes
# from {CLIENT_SECRET_ENV}, or is asked for when you sign in and then kept.
client_id = "<client id>"
# sign_in = "browser"   the default: a link to open in any browser, where you sign in as
#                       usual (single sign-on and MFA too); paste back where it lands
# sign_in = "password"  the username and password, once (from {PASSWORD_ENV}, or asked)
# username = "admin"    needed for sign_in = "password" and auth = "basic"
# redirect_uri = "{DEFAULT_REDIRECT_URI}"   must match the entry's Redirect URL
# token_cache = "file"  where the refresh token is kept: file (the default), keychain
#                       or memory
# auth = "basic"        instead of OAuth: the password with every request, where the
#                       instance allows it
# password_env = "{PASSWORD_ENV}"   another variable, for a second instance
# client_secret_env = "{CLIENT_SECRET_ENV}"
"""


@dataclass(frozen=True)
class Profile:
    """One ServiceNow instance, and the account to sign in to it with."""

    name: str
    instance: str
    username: str | None = None  # None: read from SNOW_INSTANCE_USERNAME when needed
    auth: str = "oauth"
    client_id: str | None = None  # None: read from SNOW_CLIENT_ID when signing in
    sign_in: str = "browser"
    redirect_uri: str = DEFAULT_REDIRECT_URI
    token_cache: str = DEFAULT_TOKEN_CACHE
    password_env: str = PASSWORD_ENV
    client_secret_env: str = CLIENT_SECRET_ENV
    description: str = ""

    @property
    def host(self) -> str:
        """The instance's host name, from its URL."""
        return urlsplit(self.instance).netloc

    @property
    def has_placeholder(self) -> bool:
        """Whether the instance is still the template's placeholder."""
        return self.host == PLACEHOLDER_HOST

    def require_real_instance(self) -> None:
        """A ConfigError when the instance is still the template's placeholder."""
        if self.has_placeholder:
            raise ConfigError(
                f"ServiceNow profile {self.name!r} still has the template's placeholder instance",
                hint="set its instance in the config file",
            )


@dataclass(frozen=True)
class ServiceNowConfig:
    """The parsed ``[servicenow]`` section."""

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
                f"unknown ServiceNow profile {name!r} (configured: {known})",
                hint=f"edit {self.path}" if self.path else None,
            ) from None


def instance_url(value: str, where: str) -> str:
    """``https://<name>.service-now.com``, or another https URL, without a trailing slash.

    A bare instance name (``dev12345``) means ``https://dev12345.service-now.com``.
    """
    value = value.strip()
    if _INSTANCE_NAME.fullmatch(value):
        return f"https://{value}.service-now.com"
    parts = urlsplit(value)
    # The password or token goes with every request, so plain http is never acceptable.
    if parts.scheme != "https" or not parts.netloc:
        raise ConfigError(f"{where}: instance must be an https:// URL or an instance name")
    if parts.path.strip("/") or parts.query or parts.fragment:
        raise ConfigError(f"{where}: instance must be the instance's address, with no path")
    return f"https://{parts.netloc.lower()}"


def load_config(path: Path | None = None) -> ServiceNowConfig | None:
    """Read the config file's ``[servicenow]`` section, or None when it has none."""
    return from_file(load_config_file(path))


def from_file(file: ConfigFile) -> ServiceNowConfig | None:
    """Validate the ``[servicenow]`` section; None when the file has none."""
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
    return ServiceNowConfig(path=file.path, profiles=profiles, default_profile=default)


def profile_from_env(environ: Mapping[str, str] = os.environ) -> Profile | None:
    """The ``env`` profile from ``SNOW_INSTANCE_URL`` (and friends), or None without it."""
    url = environ.get(URL_ENV, "").strip()
    if not url:
        return None
    # OAuth once there is an application to sign in through; with a password to hand,
    # it signs in with that rather than a browser.
    return Profile(
        name=ENV_PROFILE,
        instance=instance_url(url, URL_ENV),
        username=environ.get(USERNAME_ENV, "").strip() or None,
        auth="oauth" if environ.get(CLIENT_ID_ENV, "").strip() else "basic",
        sign_in="password" if environ.get(PASSWORD_ENV) else "browser",
        description=f"from {URL_ENV}",
    )


def _parse_profile(name: str, value: object, path: str) -> Profile:
    where = f"{path}: [{SECTION}.profiles.{name}]"
    check_name(name, where)
    data = table(value, where)
    reject_unknown(data, _PROFILE_KEYS, where)
    instance = text(data, "instance", where)
    if not instance:
        raise ConfigError(f"{where}: instance is required")
    auth = text(data, "auth", where) or "oauth"
    if auth not in AUTH_METHODS:
        raise ConfigError(f"{where}: auth must be one of {', '.join(AUTH_METHODS)}")
    sign_in = text(data, "sign_in", where)
    if sign_in is not None and sign_in not in SIGN_INS:
        raise ConfigError(f"{where}: sign_in must be one of {', '.join(SIGN_INS)}")
    redirect = text(data, "redirect_uri", where)
    if redirect is not None and not _redirect_ok(redirect):
        raise ConfigError(f"{where}: redirect_uri must be http://localhost... or an https:// URL")
    if auth == "basic" and (sign_in or redirect):
        raise ConfigError(f'{where}: sign_in and redirect_uri apply to auth = "oauth"')
    token_cache = text(data, "token_cache", where)
    if token_cache is not None and token_cache not in TOKEN_CACHES:
        raise ConfigError(f"{where}: token_cache must be one of {', '.join(TOKEN_CACHES)}")
    if token_cache is not None and auth != "oauth":
        raise ConfigError(
            f'{where}: token_cache applies to auth = "oauth"',
            hint="basic sign-in sends the password each time, so there is nothing to keep",
        )
    return Profile(
        name=name,
        instance=instance_url(instance, where),
        username=text(data, "username", where) or None,
        auth=auth,
        client_id=text(data, "client_id", where) or None,
        sign_in=sign_in or "browser",
        redirect_uri=redirect or DEFAULT_REDIRECT_URI,
        token_cache=token_cache or DEFAULT_TOKEN_CACHE,
        password_env=_env_name(data, "password_env", where) or PASSWORD_ENV,
        client_secret_env=_env_name(data, "client_secret_env", where) or CLIENT_SECRET_ENV,
        description=text(data, "description", where) or "",
    )


def _redirect_ok(uri: str) -> bool:
    parts = urlsplit(uri)
    if parts.scheme == "https" and parts.netloc:
        return True
    return parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}


def _env_name(data: Mapping[str, Any], key: str, where: str) -> str | None:
    value = text(data, key, where)
    if value is not None and not _ENV_NAME.fullmatch(value):
        raise ConfigError(f"{where}: {key} must be an environment variable name")
    return value
