"""Tokens for an Azure managed identity, from the endpoint of the host it runs on.

App Service and Azure Functions publish ``IDENTITY_ENDPOINT`` and ``IDENTITY_HEADER``;
virtual machines, scale sets and most other hosts use the instance metadata service
(IMDS) at 169.254.169.254. Both are plain http on a local address by design; no bearer
token is sent to either, so the http client allows them explicitly.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from datetime import datetime

import requests

from libre_devops_helpers.core.auth import AccessToken, utc_now
from libre_devops_helpers.core.errors import ApiError, AuthError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.microsoft.auth.entra import parse_token_response

IMDS_URL = "http://169.254.169.254/metadata/identity/oauth2/token"


class ManagedIdentityCredential:
    """A token provider for the managed identity of the Azure host this runs on.

    ``client_id`` picks a user-assigned identity; without it the system-assigned one is
    used. A managed identity belongs to one tenant, so ``tenant_id`` is not sent, and the
    token checks catch a profile that names a different tenant.
    """

    def __init__(
        self,
        client_id: str | None = None,
        *,
        environ: Mapping[str, str] = os.environ,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id
        self._clock = clock
        endpoint = environ.get("IDENTITY_ENDPOINT")
        header = environ.get("IDENTITY_HEADER")
        if endpoint and header:
            self.source = "App Service"
            self._url = endpoint
            self._headers = {"X-IDENTITY-HEADER": header}
            self._version = "2019-08-01"
        else:
            self.source = "IMDS"
            self._url = IMDS_URL
            self._headers = {"Metadata": "true"}
            self._version = "2018-02-01"
        # A short timeout: off Azure, IMDS never answers, and that should fail fast.
        self._api = ApiClient(
            self._url,
            None,
            name=f"managed identity ({self.source})",
            session=session,
            timeout=5.0,
            max_attempts=3,
            sleep=sleep,
            allow_http=True,
        )

    def __repr__(self) -> str:
        return f"ManagedIdentityCredential(client_id={self.client_id!r}, source={self.source!r})"

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        """A token for ``resource`` from this Azure host's identity endpoint."""
        params = {"api-version": self._version, "resource": resource}
        if self.client_id:
            params["client_id"] = self.client_id
        now = self._clock()
        try:
            data = self._api.get(self._url, params=params, headers=self._headers)
        except ApiError as exc:
            raise AuthError(
                str(exc),
                hint="managed identity only works on an Azure host with an identity assigned",
            ) from None
        return parse_token_response(data, resource, tenant_id, now=now, name=self._api.name)
