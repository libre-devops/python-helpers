"""Tokens for an app registration, straight from the Entra ID token endpoint.

Two client credential flows, for automation that has no Azure CLI sign-in:

- ``ClientSecretCredential``: a client secret, read from the environment by the caller.
- ``WorkloadIdentityCredential``: a federated token (OIDC) exchanged for an access
  token, so no secret exists at all. The federated token comes from a file (AKS and
  most CI systems) or from the GitHub Actions OIDC endpoint.

Secrets and assertions are sent in the form body only and never logged or repr'd.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.auth import AccessToken, utc_now
from libre_devops_helpers.core.errors import ApiError, AuthError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.microsoft.clouds import PUBLIC

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
# The audience Entra ID expects on a federated token.
EXCHANGE_AUDIENCE = "api://AzureADTokenExchange"


def scope_for(resource: str) -> str:
    """The v2 ``.default`` scope for a v1 resource URL."""
    return resource.rstrip("/") + "/.default"


class _TokenEndpoint:
    """POSTs a client credential grant to ``{login_url}/{tenant}/oauth2/v2.0/token``."""

    def __init__(
        self,
        login_url: str,
        *,
        name: str,
        session: requests.Session | None,
        verify: bool | str,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._api = ApiClient(
            login_url, None, name=name, session=session, verify=verify, sleep=sleep
        )
        self._name = name
        self._clock = clock

    def token(self, resource: str, tenant_id: str, form: Mapping[str, str]) -> AccessToken:
        now = self._clock()
        try:
            data = self._api.request(
                "POST",
                f"/{tenant_id}/oauth2/v2.0/token",
                form={**form, "grant_type": "client_credentials", "scope": scope_for(resource)},
            )
        except ApiError as exc:
            raise AuthError(str(exc), hint=_hint(exc)) from None
        return parse_token_response(data, resource, tenant_id, now=now, name=self._name)


def parse_token_response(
    data: Mapping[str, Any], resource: str, tenant_id: str, *, now: datetime, name: str
) -> AccessToken:
    """An AccessToken from an OAuth token response (``expires_in`` or ``expires_on``)."""
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise AuthError(f"{name}: the token response has no access_token")
    expires_in = fields.number(data.get("expires_in"))
    expires_on = fields.number(data.get("expires_on"))
    if expires_in is not None:
        expiry = now + timedelta(seconds=expires_in)
    elif expires_on is not None:
        expiry = datetime.fromtimestamp(expires_on, now.tzinfo)
    else:
        raise AuthError(f"{name}: the token response has no expiry")
    return AccessToken(token=token, expires_on=expiry, tenant_id=tenant_id, resource=resource)


class ClientSecretCredential:
    """A token provider for an app registration authenticating with a client secret."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        login_url: str = PUBLIC.login_url,
        session: requests.Session | None = None,
        verify: bool | str = True,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not client_secret:
            raise AuthError("the client secret is empty")
        self.client_id = client_id
        self._secret = client_secret
        self._endpoint = _TokenEndpoint(
            login_url,
            name="Entra ID token endpoint",
            session=session,
            verify=verify,
            clock=clock,
            sleep=sleep,
        )

    def __repr__(self) -> str:
        return f"ClientSecretCredential(client_id={self.client_id!r})"

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        """A token for ``resource``, from the client id and secret."""
        return self._endpoint.token(
            resource, tenant_id, {"client_id": self.client_id, "client_secret": self._secret}
        )


class WorkloadIdentityCredential:
    """A token provider that exchanges a federated token for an access token.

    ``assertion`` is called for every token request, because federated tokens are
    short-lived and rotated by whatever issues them.
    """

    def __init__(
        self,
        client_id: str,
        assertion: Callable[[], str],
        *,
        login_url: str = PUBLIC.login_url,
        session: requests.Session | None = None,
        verify: bool | str = True,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id
        self._assertion = assertion
        self._endpoint = _TokenEndpoint(
            login_url,
            name="Entra ID token endpoint",
            session=session,
            verify=verify,
            clock=clock,
            sleep=sleep,
        )

    def __repr__(self) -> str:
        return f"WorkloadIdentityCredential(client_id={self.client_id!r})"

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        """A token for ``resource``, exchanged for a fresh federated token (a client assertion)."""
        return self._endpoint.token(
            resource,
            tenant_id,
            {
                "client_id": self.client_id,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": self._assertion(),
            },
        )


def federated_token_file(path: Path) -> Callable[[], str]:
    """An assertion source that re-reads ``path`` each time (the file is rotated)."""

    def read() -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AuthError(f"cannot read the federated token file {path}: {exc}") from None
        if not value:
            raise AuthError(f"the federated token file {path} is empty")
        return value

    return read


def github_actions_assertion(
    request_url: str,
    request_token: str,
    *,
    audience: str = EXCHANGE_AUDIENCE,
    session: requests.Session | None = None,
    verify: bool | str = True,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[], str]:
    """An assertion source that asks the GitHub Actions OIDC endpoint for an ID token.

    ``request_url`` and ``request_token`` are the runner's ``ACTIONS_ID_TOKEN_REQUEST_URL``
    and ``ACTIONS_ID_TOKEN_REQUEST_TOKEN``; the job needs ``permissions: id-token: write``.
    """
    api = ApiClient(
        request_url,
        lambda: request_token,
        name="GitHub Actions OIDC",
        session=session,
        verify=verify,
        sleep=sleep,
    )

    def fetch() -> str:
        try:
            data = api.get(request_url, params={"audience": audience})
        except ApiError as exc:
            raise AuthError(
                str(exc), hint="the workflow job needs 'permissions: id-token: write'"
            ) from None
        value = data.get("value")
        if not isinstance(value, str) or not value:
            raise AuthError("GitHub Actions OIDC: the response has no token value")
        return value

    return fetch


def _hint(exc: ApiError) -> str | None:
    text = str(exc)
    if "AADSTS7000215" in text or "AADSTS7000222" in text:
        return "the client secret is wrong or expired; check AZURE_CLIENT_SECRET"
    if "AADSTS700016" in text:
        return "no app with this client_id exists in the tenant; check the profile's client_id"
    if "AADSTS70021" in text or "AADSTS700213" in text:
        return "no federated credential on the app matches this token's issuer and subject"
    if "AADSTS90002" in text:
        return "no such tenant: check the profile's tenant_id"
    return "check the profile's client_id and tenant_id, and the app's credentials"
