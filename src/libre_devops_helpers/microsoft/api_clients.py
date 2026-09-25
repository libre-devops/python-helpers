"""The two Microsoft APIs most features read through: Graph and Azure Resource Manager.

A feature's client subclasses one of these and so is built the same way as every other:
``create`` for a tenant, ``for_profile`` for a configured profile in its own cloud, each
asking for tokens with the API's own audience. ``API_NAME`` is how errors name the API.
"""

from __future__ import annotations

from typing import ClassVar, Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.http import ApiClient, ServiceClient
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile

# Graph error codes that say more than the HTTP status does: a 403 is as often a missing
# licence or role as a missing scope.
GRAPH_ERROR_HINTS = {
    "Authentication_RequestFromNonPremiumTenantOrB2CTenant": (
        "this needs a Microsoft Entra ID P1 or P2 licence in the tenant, which it does not "
        "have (or it is a B2C tenant), whatever the token's scopes"
    ),
    "Authentication_RequestFromUnsupportedUserRole": (
        "this is limited to some Entra roles (such as Reports Reader, Security Reader or "
        "Global Reader), and the signed-in user has none of them active: activate one with "
        "PIM if it is eligible"
    ),
}


class GraphServiceClient(ServiceClient):
    """A client that reads Microsoft Graph, in one tenant."""

    API_NAME: ClassVar[str] = "Microsoft Graph"

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        graph_url: str = PUBLIC.graph_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        """A client for ``tenant_id`` that takes its Graph tokens from ``tokens``."""
        api = ApiClient(
            graph_url,
            token_source(tokens, graph_url, tenant_id),
            name=cls.API_NAME,
            verify=verify,
            session=session,
            error_hints=GRAPH_ERROR_HINTS,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        """A client for a configured profile's tenant, in the profile's cloud."""
        return cls.create(
            tokens,
            profile.tenant_id,
            graph_url=profile.cloud.graph_url,
            verify=verify,
            session=session,
        )


class ArmServiceClient(ServiceClient):
    """A client that reads Azure Resource Manager, in one tenant."""

    API_NAME: ClassVar[str] = "Azure Resource Manager"

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        arm_url: str = PUBLIC.arm_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        """A client for ``tenant_id`` that takes its Resource Manager tokens from ``tokens``."""
        api = ApiClient(
            arm_url,
            # Resource Manager's token audience is its URL with the trailing slash.
            token_source(tokens, arm_url.rstrip("/") + "/", tenant_id),
            name=cls.API_NAME,
            verify=verify,
            session=session,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        """A client for a configured profile's tenant, in the profile's cloud."""
        return cls.create(
            tokens, profile.tenant_id, arm_url=profile.cloud.arm_url, verify=verify, session=session
        )
