"""The Atlassian Cloud client base, and the API token Jira and Confluence both read with."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Self

import requests

from libre_devops_helpers.atlassian.config import Profile
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.core.http import ApiClient, ServiceClient

TOKEN_PAGE = "https://id.atlassian.com/manage-profile/security/api-tokens"
# Atlassian's errors carry no code, so their hints go by status.
ERROR_HINTS = {
    "HTTP 401": (
        "the site did not accept the email and API token together: check the profile's email "
        f"(or JIRA_EMAIL), and that the token is current ({TOKEN_PAGE})"
    ),
    "HTTP 403": "the account can sign in but may not see this: ask for the project or space",
}


class ApiToken:
    """An Atlassian account's email and API token, sent with each request (HTTP Basic)."""

    scheme = "Basic"

    def __init__(self, email: str, token: str) -> None:
        if not email:
            raise AuthError("an API token needs its account's email")
        if not token:
            raise AuthError("the API token is empty")
        self.email = email
        self._encoded = base64.b64encode(f"{email}:{token}".encode()).decode()

    def __repr__(self) -> str:
        return f"ApiToken(email={self.email!r})"

    def authorization(self) -> str:
        """The value that follows ``Basic`` in the Authorization header."""
        return self._encoded


def token_for(profile: Profile, environ: Mapping[str, str]) -> ApiToken:
    """The profile's email with the token in its ``token_env``, or an AuthError saying how."""
    token = environ.get(profile.token_env, "").strip()
    if not token:
        raise AuthError(
            f"no Atlassian API token in {profile.token_env}",
            hint=f"create one at {TOKEN_PAGE}, then export {profile.token_env}=<token>",
        )
    return ApiToken(profile.email, token)


class AtlassianServiceClient(ServiceClient):
    """A client for one Atlassian Cloud site, reading as one account."""

    NAME = "Atlassian"

    @classmethod
    def create(
        cls,
        site: str,
        credential: ApiToken,
        *,
        session: requests.Session | None = None,
        verify: bool | str = True,
    ) -> Self:
        """A client for ``site``, sending ``credential`` with each request."""
        return cls(
            ApiClient(
                site,
                credential.authorization,
                name=cls.NAME,
                session=session,
                verify=verify,
                auth_scheme=ApiToken.scheme,
                error_hints=ERROR_HINTS,
            )
        )

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        environ: Mapping[str, str],
        *,
        session: requests.Session | None = None,
        verify: bool | str = True,
    ) -> Self:
        """A client for ``profile``'s site, with the token its ``token_env`` holds."""
        profile.require_real_site()
        return cls.create(profile.site, token_for(profile, environ), session=session, verify=verify)
