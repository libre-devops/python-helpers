"""Build the credential a profile's ``auth`` setting names.

Secrets never come from the config file. They come from the environment, under the
same names the Azure SDKs use, so a CI job configured for one works for the other.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

import requests

from libre_devops_helpers.core.auth import TokenProvider
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.core.token_store import TokenStore, open_store
from libre_devops_helpers.microsoft.auth.azure_cli import AzureCliCredential, Reauthenticate
from libre_devops_helpers.microsoft.auth.delegated import (
    DeviceCodeCredential,
    InteractiveCredential,
)
from libre_devops_helpers.microsoft.auth.entra import (
    ClientSecretCredential,
    WorkloadIdentityCredential,
    federated_token_file,
    github_actions_assertion,
)
from libre_devops_helpers.microsoft.auth.managed_identity import (
    ManagedIdentityCredential,
)
from libre_devops_helpers.microsoft.config import DELEGATED_AUTH, Profile
from libre_devops_helpers.microsoft.process import AzureCliRunner

SECRET_VARIABLE = "AZURE_CLIENT_SECRET"
TOKEN_FILE_VARIABLE = "AZURE_FEDERATED_TOKEN_FILE"
GITHUB_URL_VARIABLE = "ACTIONS_ID_TOKEN_REQUEST_URL"
GITHUB_TOKEN_VARIABLE = "ACTIONS_ID_TOKEN_REQUEST_TOKEN"


def credential_for(
    profile: Profile,
    *,
    runner: AzureCliRunner | None = None,
    session: requests.Session | None = None,
    verify: bool | str = True,
    environ: Mapping[str, str] = os.environ,
    notify: Callable[[str], None] | None = None,
    reauthenticate: Reauthenticate | None = None,
    token_store: TokenStore | None = None,
) -> TokenProvider:
    """The token provider for ``profile``. Raises AuthError when its inputs are missing.

    ``reauthenticate`` is offered to the Azure CLI credential, to sign the CLI in again
    when its session has lapsed; see AzureCliCredential. ``token_store`` keeps an
    interactive or device-code sign-in between commands; without it, the store the
    profile's ``token_cache`` names is opened.
    """
    login_url = profile.cloud.login_url
    if profile.auth == "azure-cli":
        return AzureCliCredential(runner, reauthenticate=reauthenticate)
    if profile.auth == "managed-identity":
        return ManagedIdentityCredential(profile.client_id, environ=environ, session=session)

    client_id = profile.client_id
    if client_id is None:
        raise AuthError(f"profile {profile.name!r} uses auth = {profile.auth!r} without client_id")

    if profile.auth in DELEGATED_AUTH:
        flow = InteractiveCredential if profile.auth == "interactive" else DeviceCodeCredential
        return flow(
            client_id,
            login_url=login_url,
            session=session,
            verify=verify,
            notify=notify,
            store=token_store or open_store(profile.token_cache, environ=environ),
        )

    if profile.auth == "client-secret":
        return ClientSecretCredential(
            client_id,
            _client_secret(profile, environ),
            login_url=login_url,
            session=session,
            verify=verify,
        )
    if profile.auth == "workload-identity":
        return WorkloadIdentityCredential(
            client_id,
            _federated_assertion(profile, environ, session, verify),
            login_url=login_url,
            session=session,
            verify=verify,
        )
    raise AuthError(f"profile {profile.name!r} has an unknown auth method {profile.auth!r}")


def _client_secret(profile: Profile, environ: Mapping[str, str]) -> str:
    """The secret from the environment: the config file never holds one."""
    secret = environ.get(SECRET_VARIABLE, "")
    if not secret:
        raise AuthError(
            f"profile {profile.name!r} needs a client secret",
            hint=f"set {SECRET_VARIABLE}; the config file never holds secrets",
        )
    return secret


def _federated_assertion(
    profile: Profile,
    environ: Mapping[str, str],
    session: requests.Session | None,
    verify: bool | str,
) -> Callable[[], str]:
    """Where the federated token comes from: a file (Kubernetes and most CI), else
    GitHub Actions' own token endpoint."""
    token_file = environ.get(TOKEN_FILE_VARIABLE)
    if token_file:
        return federated_token_file(Path(token_file))
    if environ.get(GITHUB_URL_VARIABLE) and environ.get(GITHUB_TOKEN_VARIABLE):
        return github_actions_assertion(
            environ[GITHUB_URL_VARIABLE],
            environ[GITHUB_TOKEN_VARIABLE],
            session=session,
            verify=verify,
        )
    raise AuthError(
        f"profile {profile.name!r} has no federated token to exchange",
        hint=(
            f"set {TOKEN_FILE_VARIABLE}, or run in GitHub Actions with "
            "'permissions: id-token: write'"
        ),
    )
