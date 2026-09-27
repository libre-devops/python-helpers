"""The CLI's Atlassian state: profiles and clients, for one invocation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar

import requests

from libre_devops_helpers.atlassian import (
    EMAIL_ENV,
    ENV_PROFILE,
    SITE_ENV,
    AtlassianConfig,
    Profile,
    from_file,
    profile_from_env,
)
from libre_devops_helpers.atlassian.confluence import ConfluenceClient
from libre_devops_helpers.atlassian.jira import JiraClient
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.config import ConfigFile
from libre_devops_helpers.core.errors import ConfigError


class _Closeable(Protocol):
    def close(self) -> None:
        """Release the connection pool."""


_C = TypeVar("_C", bound=_Closeable)


class Host(Protocol):
    """What this needs from the CLI's Runtime (a Protocol, as runtime.py imports this)."""

    @property
    def environ(self) -> Mapping[str, str]:
        """The environment variables the command sees."""

    @property
    def session(self) -> requests.Session | None:
        """The HTTP session to use, or None for each client's own (tests pass one)."""

    def optional_config_file(self) -> ConfigFile | None:
        """The config file, or None when there is none."""

    def verify(self) -> bool | str:
        """TLS verification for requests: True, or a CA bundle's path."""

    def track(self, client: _C) -> _C:
        """Close ``client`` when the command ends, and return it."""


class AtlassianRuntime:
    """Profiles and clients for Jira and Confluence, created as they are needed."""

    def __init__(self, runtime: Host) -> None:
        self.runtime = runtime

    def config(self) -> AtlassianConfig | None:
        """The ``[atlassian]`` section, or None without a config file or section."""
        file = self.runtime.optional_config_file()
        return from_file(file) if file is not None else None

    def profiles(self) -> list[Profile]:
        """Every profile: the configured ones, and ``env`` when JIRA_INSTANCE is set."""
        config = self.config()
        found = list(config.profiles.values()) if config else []
        env = profile_from_env(self.runtime.environ)
        if env is not None and all(profile.name != ENV_PROFILE for profile in found):
            found.append(env)
        return found

    def profile(self, name: str | None) -> Profile:
        """The named profile, else default_profile, else the ``env`` one."""
        config = self.config()
        env = profile_from_env(self.runtime.environ)
        if name:
            if (
                name == ENV_PROFILE
                and env is not None
                and (config is None or name not in config.profiles)
            ):
                return env
            if config is None:
                raise ConfigError(f"unknown Atlassian profile {name!r}", hint=_SETUP)
            return config.get(name)
        if config is not None and config.default_profile:
            return config.get(config.default_profile)
        if env is not None:
            return env
        if config is not None and len(config.profiles) == 1:
            return next(iter(config.profiles.values()))
        raise ConfigError("no Atlassian profile selected", hint=_SETUP)

    def jira(self, profile: Profile) -> JiraClient:
        """A Jira client for ``profile``, closed when the command ends."""
        return self.runtime.track(
            JiraClient.for_profile(
                profile,
                self.runtime.environ,
                session=self.runtime.session,
                verify=self.runtime.verify(),
            )
        )

    def confluence(self, profile: Profile) -> ConfluenceClient:
        """A Confluence client for ``profile``, closed when the command ends."""
        return self.runtime.track(
            ConfluenceClient.for_profile(
                profile,
                self.runtime.environ,
                session=self.runtime.session,
                verify=self.runtime.verify(),
            )
        )


_SETUP = (
    f"export {SITE_ENV} and {EMAIL_ENV} (and the token), or add an [atlassian] section: "
    f"{brand.command('config init')} writes one to fill in"
)
