"""Per-invocation state for the CLI.

``Runtime`` holds what every vendor shares: the config file, TLS settings, the HTTP
session, the environment, the clock, and the clients to close at exit. Each vendor has
its own runtime hanging off it (``runtime.microsoft``), holding that vendor's profiles,
credentials and clients. Everything is created lazily, so ``--help`` never touches a
CLI tool or the network.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import requests
import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.servicenow_runtime import ServiceNowRuntime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import CachingTokenProvider
from libre_devops_helpers.core.browser import can_launch_browser
from libre_devops_helpers.core.config import ConfigFile, load_config_file
from libre_devops_helpers.core.errors import ConfigError, ConfigNotFoundError
from libre_devops_helpers.core.token_store import TokenStore
from libre_devops_helpers.microsoft.auth import credential_for
from libre_devops_helpers.microsoft.azcli import AzCli
from libre_devops_helpers.microsoft.azure import AzureClient
from libre_devops_helpers.microsoft.config import SECTION as MICROSOFT
from libre_devops_helpers.microsoft.config import MicrosoftConfig, Profile
from libre_devops_helpers.microsoft.config import from_file as microsoft_from_file
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.graph import GraphClient
from libre_devops_helpers.microsoft.incidents import IncidentsClient
from libre_devops_helpers.microsoft.intune import IntuneClient
from libre_devops_helpers.microsoft.keyvault import KeyVaultClient
from libre_devops_helpers.microsoft.loganalytics import LogAnalyticsClient
from libre_devops_helpers.microsoft.logicapps import LogicAppsClient
from libre_devops_helpers.microsoft.pim import AzurePimClient, GraphPimClient
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner
from libre_devops_helpers.microsoft.xdr import XdrClient
from libre_devops_helpers.servicenow.config import SECTION as SERVICENOW

# Every vendor section the config file may hold. Anything else at the top level is a typo.
SECTIONS = (MICROSOFT, SERVICENOW)


def _prompt(message: str) -> None:
    typer.secho(message, fg="cyan", err=True)


def _on_a_terminal() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def _confirm(question: str) -> bool:
    return typer.confirm(typer.style(question, fg="cyan"), default=True, err=True)


def _ask(question: str, secret: bool) -> str:
    return str(typer.prompt(typer.style(question, fg="cyan"), hide_input=secret, err=True))


# LDO_REAUTH: unset (or "prompt") asks on a terminal, "device-code" asks and then signs
# in with a device code, and "off" never asks, so a lapsed sign-in is an error at once.
_REAUTH_OFF = {"off", "never", "no", "false", "0"}


class _Closeable(Protocol):
    def close(self) -> None:
        """Release the connection pool."""


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
    # Whether someone is there to answer a question, and how to ask it.
    interactive: Callable[[], bool] = _on_a_terminal
    confirm: Callable[[str], bool] = _confirm
    # Asks a question and returns the answer; the flag hides what is typed (a secret).
    ask: Callable[[str, bool], str] = _ask
    # Whether a browser can be opened here, and how to open one on a sign-in link.
    has_browser: Callable[[], bool] = can_launch_browser
    open_browser: Callable[[str], object] = webbrowser.open
    # Tests replace the store a profile's token_cache would open.
    token_store: TokenStore | None = None
    _file: ConfigFile | None = field(default=None, init=False)
    _microsoft: MicrosoftRuntime | None = field(default=None, init=False)
    _servicenow: ServiceNowRuntime | None = field(default=None, init=False)
    _closers: list[Callable[[], None]] = field(default_factory=list, init=False)

    @property
    def microsoft(self) -> MicrosoftRuntime:
        if self._microsoft is None:
            self._microsoft = MicrosoftRuntime(self)
        return self._microsoft

    @property
    def servicenow(self) -> ServiceNowRuntime:
        if self._servicenow is None:
            self._servicenow = ServiceNowRuntime(self)
        return self._servicenow

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
                reauthenticate=self._reauthenticate,
                token_store=self.runtime.token_store,
            )
            self._tokens[profile.name] = CachingTokenProvider(credential)
        return self._tokens[profile.name]

    def sign_out(self, profile: Profile) -> bool:
        """Forget the sign-in ``profile`` keeps between commands. True when it had one."""
        credential = credential_for(
            profile,
            runner=self.runtime.az_runner,
            session=self.runtime.session,
            verify=self.runtime.verify(),
            environ=self.runtime.environ,
            notify=self.runtime.notify,
            token_store=self.runtime.token_store,
        )
        forget = getattr(credential, "sign_out", None)
        return bool(forget(profile.tenant_id)) if callable(forget) else False

    def _reauthenticate(self, tenant_id: str, reason: str) -> bool:
        """Offer to sign the Azure CLI in to ``tenant_id`` again, then carry on.

        Only on a terminal, and only from the main thread (a worker must not block on a
        question). The CLI's active account is put back afterwards, since ``az login``
        changes it and other shells rely on it.
        """
        mode = self.runtime.environ.get(brand.env_var("REAUTH"), "").strip().lower()
        if mode in _REAUTH_OFF or not self.runtime.interactive():
            return False
        if threading.current_thread() is not threading.main_thread():
            return False
        if not self.runtime.confirm(
            f"The Azure CLI's sign-in to tenant {tenant_id} has lapsed: {reason}. "
            "Sign in again now?"
        ):
            return False
        try:
            previous = self.az.current_account()
        except AzCliError:
            previous = None
        self.az.login(tenant_id, device_code=mode == "device-code", allow_no_subscriptions=True)
        if previous is not None:
            try:
                self.az.set_account(previous.id)
            except AzCliError as exc:
                render.warn(f"signed in, but could not restore the active account: {exc}")
        return True

    def _options(self) -> dict[str, object]:
        return {"verify": self.runtime.verify(), "session": self.runtime.session}

    def entra(self, profile: Profile) -> EntraClient:
        return self.runtime.track(
            EntraClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def graph(self, profile: Profile) -> GraphClient:
        return self.runtime.track(
            GraphClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def logicapps(self, profile: Profile) -> LogicAppsClient:
        return self.runtime.track(
            LogicAppsClient.for_profile(profile, self.tokens(profile), **self._options())
        )

    def incidents(self, profile: Profile) -> IncidentsClient:
        return self.runtime.track(
            IncidentsClient.for_profile(profile, self.tokens(profile), **self._options())
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
