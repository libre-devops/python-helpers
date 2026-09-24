"""The CLI's ServiceNow state: profiles, sign-ins and clients, for one invocation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import CachingTokenProvider, token_source
from libre_devops_helpers.core.errors import ConfigError
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

if TYPE_CHECKING:
    from libre_devops_helpers.cli.runtime import Runtime


class ServiceNowRuntime:
    """Profiles, credentials and clients for ServiceNow, created as they are needed."""

    def __init__(self, runtime: Runtime) -> None:
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
        credential = self.credential(profile)
        options = {"session": self.runtime.session, "verify": self.runtime.verify()}
        if isinstance(credential, BasicCredential):
            client = TableClient.create(
                profile.instance, credential.authorization, scheme="Basic", **options
            )
        else:
            client = TableClient.create(
                profile.instance,
                token_source(self.tokens(profile), profile.instance, ""),
                **options,
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
        return InstanceClient(self.tables(profile))

    @staticmethod
    def oauth_hint(profile: Profile) -> str:
        """How to move ``profile`` from basic sign-in to OAuth."""
        if profile.name == ENV_PROFILE:
            return (
                f"set {CLIENT_ID_ENV} to the application registry entry's client id "
                f"(and {CLIENT_SECRET_ENV}, or let sign-in ask for it)"
            )
        return 'set auth = "oauth" and a client_id on the profile (see the README)'

    @staticmethod
    def _setup_hint() -> str:
        return (
            f"set {URL_ENV}, or add a [servicenow] profile ({brand.command('config init')} "
            "writes a template)"
        )
