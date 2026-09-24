"""Per-invocation state for the CLI.

``Runtime`` holds what every vendor shares: the config file, TLS settings, the HTTP
session, the environment, the clock, and the clients to close at exit. Each vendor has
its own runtime hanging off it (``runtime.microsoft``), holding that vendor's profiles,
credentials and clients. Everything is created lazily, so ``--help`` never touches a
CLI tool or the network.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import requests
import typer

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import CachingTokenProvider
from libre_devops_helpers.core.config import ConfigFile, load_config_file
from libre_devops_helpers.core.errors import ConfigError, ConfigNotFoundError
from libre_devops_helpers.microsoft.auth import credential_for
from libre_devops_helpers.microsoft.azcli import AzCli
from libre_devops_helpers.microsoft.azure import AzureClient
from libre_devops_helpers.microsoft.config import SECTION as MICROSOFT
from libre_devops_helpers.microsoft.config import MicrosoftConfig, Profile
from libre_devops_helpers.microsoft.config import from_file as microsoft_from_file
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.intune import IntuneClient
from libre_devops_helpers.microsoft.keyvault import KeyVaultClient
from libre_devops_helpers.microsoft.loganalytics import LogAnalyticsClient
from libre_devops_helpers.microsoft.pim import AzurePimClient, GraphPimClient
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner
from libre_devops_helpers.microsoft.xdr import XdrClient

# Every vendor section the config file may hold. Anything else at the top level is a typo.
SECTIONS = (MICROSOFT,)


def _prompt(message: str) -> None:
    typer.secho(message, fg="cyan", err=True)


class _Closeable(Protocol):
    def close(self) -> None: ...


C = TypeVar("C", bound=_Closeable)


@dataclass
class Runtime:
    """What every command shares.

    Tests pass an ``az_runner`` wrapping a fake subprocess, a ``session`` routing HTTP
    through a fake adapter, an ``environ`` for credentials that read the environment, and
    a ``clock`` and ``sleep`` so a watch runs without waiting.
    """

    config_path: Path | None = None
    az_runner: AzureCliRunner = field(default_factory=AzureCliRunner)
    session: requests.Session | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    # Where a credential shows a sign-in prompt (a URL, or a device code): stderr.
    notify: Callable[[str], None] = _prompt
    _file: ConfigFile | None = field(default=None, init=False)
    _microsoft: MicrosoftRuntime | None = field(default=None, init=False)
    _closers: list[Callable[[], None]] = field(default_factory=list, init=False)

    @property
    def microsoft(self) -> MicrosoftRuntime:
        if self._microsoft is None:
            self._microsoft = MicrosoftRuntime(self)
        return self._microsoft

    def config_file(self) -> ConfigFile:
        """The config file, loaded once. Raises ConfigNotFoundError when it is absent."""
        if self._file is None:
            self._file = load_config_file(self.config_path, sections=SECTIONS)
        return self._file

    def optional_config_file(self) -> ConfigFile | None:
        """The config file, or None when it does not exist (other errors still raise)."""
        try:
            return self.config_file()
        except ConfigNotFoundError:
            return None

    def verify(self) -> bool | str:
        """TLS verification for requests: True, or the config's CA bundle path."""
        file = self.optional_config_file()
        if file is None or file.ca_bundle is None:
            return True
        if not file.ca_bundle.is_file():
            raise ConfigError(f"ca_bundle not found: {file.ca_bundle}")
        return str(file.ca_bundle)

    def track(self, client: C) -> C:
        """Close ``client`` when the command finishes."""
        self._closers.append(client.close)
        return client

    def close(self) -> None:
        while self._closers:
            self._closers.pop()()


class MicrosoftRuntime:
    """Microsoft profiles, credentials and clients for one invocation."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._config: MicrosoftConfig | None = None
        self._tokens: dict[str, CachingTokenProvider] = {}

    @property
    def az(self) -> AzCli:
        """The Azure CLI's accounts, for profile switching and the active account."""
        return AzCli(self.runtime.az_runner)

    def config(self) -> MicrosoftConfig:
        """The ``[microsoft]`` section, parsed once."""
        if self._config is None:
            self._config = microsoft_from_file(self.runtime.config_file())
        return self._config

    def optional_config(self) -> MicrosoftConfig | None:
        """The ``[microsoft]`` section, or None when there is no config file or section."""
        file = self.runtime.optional_config_file()
        if file is None or file.section(MICROSOFT) is None:
            return None
        return self.config()

    def profile(self, name: str | None) -> Profile:
        """The profile to act on.

        ``name`` (from --profile or LDO_PROFILE) wins, then the section's
        default_profile, then the Azure CLI's active account as an unnamed profile.
        """
        if name:
            profile = self.config().get(name)
        else:
            config = self.optional_config()
            if config is not None and config.default_profile:
                profile = config.get(config.default_profile)
            else:
                return self._active_account_profile()
        profile.require_real_ids()
        return profile

    def tokens(self, profile: Profile) -> CachingTokenProvider:
        """The profile's credential, wrapped in a cache shared by every client."""
        if profile.name not in self._tokens:
            credential = credential_for(
                profile,
                runner=self.runtime.az_runner,
                session=self.runtime.session,
                verify=self.runtime.verify(),
                environ=self.runtime.environ,
                notify=self.runtime.notify,
            )
            self._tokens[profile.name] = CachingTokenProvider(credential)
        return self._tokens[profile.name]

    def _options(self) -> dict[str, object]:
        return {"verify": self.runtime.verify(), "session": self.runtime.session}

    def entra(self, profile: Profile) -> EntraClient:
        return self.runtime.track(
            EntraClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def xdr(self, profile: Profile) -> XdrClient:
        return self.runtime.track(
            XdrClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def intune(self, profile: Profile) -> IntuneClient:
        return self.runtime.track(
            IntuneClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def azure(self, profile: Profile) -> AzureClient:
        return self.runtime.track(
            AzureClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def keyvault(self, profile: Profile, vault: str) -> KeyVaultClient:
        return self.runtime.track(
            KeyVaultClient.for_profile(profile, self.tokens(profile), vault, **self._options())
        )

    def logs(self, profile: Profile) -> LogAnalyticsClient:
        return self.runtime.track(
            LogAnalyticsClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def azure_pim(self, profile: Profile) -> AzurePimClient:
        return self.runtime.track(
            AzurePimClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def graph_pim(self, profile: Profile) -> GraphPimClient:
        return self.runtime.track(
            GraphPimClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def subscription_ids(self, profile: Profile, chosen: list[str] | None = None) -> list[str]:
        """The subscriptions an Azure command covers: ``chosen``, the profile's pinned one,
        or every subscription the credential can see in the profile's tenant."""
        if chosen:
            return chosen
        if profile.subscription_id:
            return [profile.subscription_id]
        return [item.id for item in self.azure(profile).subscriptions(profile.tenant_id)]

    def _active_account_profile(self) -> Profile:
        account = self.az.current_account()
        if account is None:
            raise AzCliError(
                "no profile selected and the Azure CLI is not signed in",
                hint="pass --profile, set default_profile, or run "
                f"{brand.command('az use <profile>')}",
            )
        return Profile(
            name="az-active",
            tenant_id=account.tenant_id,
            subscription_id=None if account.tenant_level else account.id,
            description="the Azure CLI's active account",
        )
