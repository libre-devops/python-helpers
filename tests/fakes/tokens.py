"""Unsigned JWTs with chosen claims, and a token provider that hands them out."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fakes.ids import TENANT
from libre_devops_helpers.core.auth import AccessToken


def make_jwt(claims: dict[str, Any], header: dict[str, Any] | None = None) -> str:
    """An unsigned JWT carrying ``claims``; the signature segment is junk."""

    def segment(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{segment(header or {'alg': 'RS256', 'typ': 'JWT'})}.{segment(claims)}.signature"


def graph_claims(**overrides: Any) -> dict[str, Any]:
    """Claims of a healthy delegated Graph token for TENANT, valid for an hour."""
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "aud": "https://graph.microsoft.com",
        "tid": TENANT,
        "iss": f"https://sts.windows.net/{TENANT}/",
        "upn": "analyst@example.com",
        "appid": "04b07795-8ddb-461a-bbee-02f9e1bf7b46",
        "scp": "Device.Read.All GroupMember.Read.All",
        "iat": now - 60,
        "nbf": now - 60,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


class StaticTokens:
    """A TokenProvider handing out a fixed token and recording what was asked for."""

    def __init__(self, token: str = "token-value") -> None:
        self.token = token
        self.calls: list[tuple[str, str]] = []

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        self.calls.append((resource, tenant_id))
        expires = datetime.now(UTC) + timedelta(hours=1)
        return AccessToken(self.token, expires, tenant_id, resource)
