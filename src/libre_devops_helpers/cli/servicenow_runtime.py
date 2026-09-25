"""The CLI's ServiceNow state: profiles, sign-ins and clients, for one invocation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar

import requests

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import CachingTokenProvider, token_source
from libre_devops_helpers.core.config import ConfigFile
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.core.token_store import TokenStore
from libre_devops_helpers.servicenow import (
    BasicCredential,
    Credential,
    OAuthCredential,
    Profile,
    ServiceNowConfig,
    TableClient,
    credential_for,
    from_file,
    profile_from_env,
)
from libre_devops_helpers.servicenow.config import (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    ENV_PROFILE,
    URL_ENV,
)
from libre_devops_helpers.servicenow.instance import InstanceClient


class _Closeable(Protocol):
    def close(self) -> None:
        """Release the connection pool."""


_C = TypeVar("_C", bound=_Closeable)


class Host(Protocol):
    """What this needs from the CLI's Runtime.

    A Protocol, so this module does not import runtime.py, which imports this one.
    """

    # Read-only properties, so a dataclass's plain fields satisfy them.
    @property
    def environ(self) -> Mapping[str, str]:
        """The environment variables the command sees."""

    @property
    def session(self) -> requests.Session | None:
        """The HTTP session to use, or None for each client's own (tests pass one)."""

    @property
    def token_store(self) -> TokenStore | None:
        """Where sign-ins are kept, instead of each profile's token_cache (tests pass one)."""

    @property
    def notify(self) -> Callable[[str], None]:
        """Shows a sign-in prompt, such as a link to open, to the person."""

    @property
    def interactive(self) -> Callable[[], bool]:
        """Whether someone is there to answer a question."""

    @property
    def ask(self) -> Callable[[str, bool], str]:
        """Asks the person a question, hiding what they type when told to."""

    @property
    def has_browser(self) -> Callable[[], bool]:
        """Whether a browser can be opened here."""

    @property
    def open_browser(self) -> Callable[[str], object]:
        """Opens a link in a browser."""

    def optional_config_file(self) -> ConfigFile | None:
        """The config file, or None when there is none."""

    def verify(self) -> bool | str:
        """TLS verification for requests: True, or a CA bundle's path."""

    def track(self, client: _C) -> _C:
        """Close ``client`` when the command ends, and return it."""


class ServiceNowRuntime:
    """Profiles, credentials and clients for ServiceNow, created as they are needed."""

    def __init__(self, runtime: Host) -> None:
        self.runtime = runtime
        self._credentials: dict[str, Credential] = {}
        self._tokens: dict[str, CachingTokenProvider] = {}

    def config(self) -> ServiceNowConfig | None:
        """The ``[servicenow]`` section, or None without a config file or section."""
        file = self.runtime.optional_config_file()
        return from_file(file) if file is not None else None

    def profiles(self) -> list[Profile]:
        """Every profile: the configured ones, and ``env`` when SNOW_INSTANCE_URL is set."""
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
            if config is not None and name in config.profiles:
                selected = config.get(name)
            elif name == ENV_PROFILE and env is not None:
                selected = env
            elif config is not None:
                selected = config.get(name)  # raises, listing the known profiles
            else:
                raise ConfigError(f"unknown ServiceNow profile {name!r}", hint=self._setup_hint())
        elif config is not None and config.default_profile:
            selected = config.get(config.default_profile)
        elif env is not None:
            selected = env
        elif config is not None and len(config.profiles) == 1:
            selected = next(iter(config.profiles.values()))
        else:
            raise ConfigError("no ServiceNow profile selected", hint=self._setup_hint())
        selected.require_real_instance()
        return selected

    def credential(self, profile: Profile) -> Credential:
        """The credential for ``profile``, made once in a run and reused."""
        if profile.name not in self._credentials:
            runtime = self.runtime
            self._credentials[profile.name] = credential_for(
                profile,
                environ=runtime.environ,
                store=runtime.token_store,
                ask=runtime.ask if runtime.interactive() else None,
                session=runtime.session,
                verify=runtime.verify(),
                notify=runtime.notify,
                sign_in_hint=f"run {brand.command(f'snow sign-in -p {profile.name}')}",
                has_browser=runtime.has_browser,
                open_browser=runtime.open_browser,
            )
        return self._credentials[profile.name]

    def tables(self, profile: Profile) -> TableClient:
        """A Table API client for ``profile``, signed in by its credential, closed when the command
        ends."""
        credential = self.credential(profile)
        session, verify = self.runtime.session, self.runtime.verify()
        if isinstance(credential, BasicCredential):
            client = TableClient.create(
                profile.instance,
                credential.authorization,
                scheme="Basic",
                session=session,
                verify=verify,
            )
        else:
            client = TableClient.create(
                profile.instance,
                token_source(self.tokens(profile), profile.instance, ""),
                session=session,
                verify=verify,
            )
        return self.runtime.track(client)

    def tokens(self, profile: Profile) -> CachingTokenProvider:
        """The OAuth profile's tokens, cached for the command."""
        credential = self.credential(profile)
        if not isinstance(credential, OAuthCredential):
            raise ConfigError(
                f"ServiceNow profile {profile.name!r} uses basic sign-in, which has no token",
                hint=self.oauth_hint(profile),
            )
        if profile.name not in self._tokens:
            self._tokens[profile.name] = CachingTokenProvider(credential)
        return self._tokens[profile.name]

    def instance(self, profile: Profile) -> InstanceClient:
        """An instance client for ``profile``, over its Table API client."""
        return InstanceClient(self.tables(profile))

    @staticmethod
    def oauth_hint(profile: Profile) -> str:
        """How to move ``profile`` from basic sign-in to OAuth."""
        if profile.name == ENV_PROFILE:
            return (
                f"set {CLIENT_ID_ENV} to the application registry entry's client id "
                f"(and {CLIENT_SECRET_ENV}, or let sign-in ask for it)"
            )
        return f'set auth = "oauth" and a client_id on the profile (see {brand.docs("servicenow")})'

    @staticmethod
    def _setup_hint() -> str:
        return (
            f"set {URL_ENV}, or add a [servicenow] profile ({brand.command('config init')} "
            "writes a template)"
        )
