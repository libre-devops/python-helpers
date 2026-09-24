"""Decode an Entra ID access token and check it is the token you meant to get.

Only the claims are inspected; the signature is NOT verified. The checks answer
"is this token for the right API and tenant, in date, with the permissions this
tool needs?", not "is this token genuine?". Microsoft Graph tokens cannot be
signature-checked by a client in any case.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from libre_devops_helpers.core.errors import TokenError
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.resources import (
    Requirement,
    Resource,
    normalise_audience,
)

Status = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class DecodedToken:
    """The header and claims of a JWT, with accessors for the common claims."""

    header: Mapping[str, Any]
    claims: Mapping[str, Any]

    def timestamp(self, claim: str) -> datetime | None:
        """A NumericDate claim (``exp``, ``nbf``, ``iat``) as an aware UTC datetime."""
        value = self.claims.get(claim)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return datetime.fromtimestamp(value, UTC)

    @property
    def expires_at(self) -> datetime | None:
        return self.timestamp("exp")

    @property
    def not_before(self) -> datetime | None:
        return self.timestamp("nbf")

    @property
    def issued_at(self) -> datetime | None:
        return self.timestamp("iat")

    @property
    def audiences(self) -> tuple[str, ...]:
        aud = self.claims.get("aud")
        if isinstance(aud, str):
            return (aud,)
        if isinstance(aud, list):
            return tuple(str(item) for item in aud)
        return ()

    @property
    def tenant_id(self) -> str:
        return str(self.claims.get("tid", ""))

    @property
    def issuer(self) -> str:
        return str(self.claims.get("iss", ""))

    @property
    def scopes(self) -> tuple[str, ...]:
        """Delegated permissions (``scp``)."""
        scp = self.claims.get("scp")
        return tuple(scp.split()) if isinstance(scp, str) else ()

    @property
    def roles(self) -> tuple[str, ...]:
        """Application permissions (``roles``)."""
        roles = self.claims.get("roles")
        return tuple(str(role) for role in roles) if isinstance(roles, list) else ()

    @property
    def principal(self) -> str:
        """Who the token is for: a user name for delegated tokens, else an app id."""
        for claim in ("upn", "unique_name", "preferred_username", "appid", "azp", "oid"):
            value = self.claims.get(claim)
            if isinstance(value, str) and value:
                return value
        return ""

    @property
    def app_id(self) -> str:
        """The client application that requested the token."""
        return str(self.claims.get("appid") or self.claims.get("azp") or "")

    @property
    def identity_type(self) -> str:
        """``user`` (delegated), ``app`` (application), or ``unknown``."""
        idtyp = self.claims.get("idtyp")
        if isinstance(idtyp, str) and idtyp:
            return idtyp
        if self.scopes:
            return "user"
        return "app" if self.roles else "unknown"


@dataclass(frozen=True)
class Check:
    """The outcome of one token check."""

    name: str
    status: Status
    detail: str


def decode_token(token: str) -> DecodedToken:
    """Decode a JWT without verifying it. Accepts an optional ``Bearer`` prefix."""
    raw = token.strip()
    if raw[:7].lower() == "bearer ":
        raw = raw[7:].strip()
    parts = raw.split(".")
    if len(parts) == 5:
        raise TokenError("this is an encrypted token (JWE); its claims cannot be read")
    if len(parts) != 3:
        raise TokenError("not a JWT: expected three dot-separated parts")
    return DecodedToken(header=_segment(parts[0], "header"), claims=_segment(parts[1], "payload"))


def _segment(value: str, name: str) -> dict[str, Any]:
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (binascii.Error, ValueError) as exc:
        raise TokenError(f"cannot decode the token {name}: {exc}") from None
    if not isinstance(data, dict):
        raise TokenError(f"the token {name} is not a JSON object")
    return data


def validate_token(
    token: DecodedToken,
    *,
    resource: Resource | None = None,
    tenant_id: str | None = None,
    required: Iterable[str] = (),
    requirements: Iterable[Requirement] = (),
    now: datetime | None = None,
    clock_skew: timedelta = timedelta(minutes=1),
    expiry_warning: timedelta = timedelta(minutes=5),
) -> list[Check]:
    """Check a decoded token's claims.

    Always checks expiry, not-before and that the issuer matches the token's own
    tenant. With ``resource`` it checks the audience, and warns for each of the
    ``requirements`` for that resource the token does not cover (so it says which
    features the token can serve). With ``tenant_id`` it checks the tenant. Each name
    in ``required`` must appear in ``scp`` or ``roles``.
    """
    now = now or datetime.now(UTC)
    checks: list[Check] = []

    expires = token.expires_at
    if expires is None:
        checks.append(Check("expiry", "fail", "no exp claim"))
    elif expires <= now:
        checks.append(Check("expiry", "fail", f"expired {format_duration(now - expires)} ago"))
    elif expires - now <= expiry_warning:
        checks.append(Check("expiry", "warn", f"expires in {format_duration(expires - now)}"))
    else:
        checks.append(Check("expiry", "pass", f"expires in {format_duration(expires - now)}"))

    not_before = token.not_before
    if not_before is not None and not_before - now > clock_skew:
        checks.append(
            Check("not-before", "fail", f"not valid for {format_duration(not_before - now)}")
        )

    if token.tenant_id:
        if token.tenant_id.lower() in token.issuer.lower():
            checks.append(Check("issuer", "pass", token.issuer))
        else:
            checks.append(
                Check("issuer", "fail", f"{token.issuer!r} does not match tid {token.tenant_id}")
            )

    if tenant_id is not None:
        if token.tenant_id.lower() == tenant_id.lower():
            checks.append(Check("tenant", "pass", token.tenant_id))
        else:
            checks.append(
                Check("tenant", "fail", f"tid {token.tenant_id or '(none)'}, expected {tenant_id}")
            )

    if resource is not None:
        checks.append(_audience_check(token, resource))

    granted = {permission.casefold() for permission in (*token.scopes, *token.roles)}
    if resource is not None:
        relevant = [item for item in requirements if item.resource == resource.key]
        checks.extend(_permission_checks(relevant, granted, {*token.scopes, *token.roles}))
    for permission in required:
        if permission.casefold() in granted:
            checks.append(Check(f"requires {permission}", "pass", "present"))
        else:
            checks.append(Check(f"requires {permission}", "fail", "not in scp or roles"))

    return checks


def passed(checks: Iterable[Check], *, strict: bool = False) -> bool:
    """True when no check failed (and, with ``strict``, none warned)."""
    bad = {"fail", "warn"} if strict else {"fail"}
    return not any(check.status in bad for check in checks)


def _audience_check(token: DecodedToken, resource: Resource) -> Check:
    audiences = token.audiences
    if any(normalise_audience(aud) in resource.audiences for aud in audiences):
        return Check("audience", "pass", f"{', '.join(audiences)} is {resource.key}")
    return Check(
        "audience",
        "fail",
        f"{', '.join(audiences) or '(none)'} is not {resource.key} ({resource.url})",
    )


def _permission_checks(
    requirements: list[Requirement], granted: set[str], names: set[str]
) -> list[Check]:
    if not requirements:
        return []
    if not granted:
        return [
            Check(
                "permissions",
                "warn",
                "no scp or roles claim; access then rests on the service's own RBAC",
            )
        ]
    if granted == {"user_impersonation"}:
        # A delegated grant with no granular scopes, as the Azure CLI gets for Defender:
        # what the user can do is decided by their role in the service, not by the token.
        return [
            Check(
                "permissions",
                "warn",
                "only user_impersonation; access then rests on your role in the service",
            )
        ]
    by_name = {name.casefold(): name for name in names}
    checks: list[Check] = []
    for requirement in requirements:
        via: list[str] = []
        missing: list[tuple[str, ...]] = []
        for group in requirement.all_of:
            match = next((p for p in group if p.casefold() in granted), None)
            if match is None:
                missing.append(group)
            else:
                via.append(by_name.get(match.casefold(), match))
        name = f"permissions: {requirement.feature}"
        if missing:
            needs = "; ".join("one of " + ", ".join(group) for group in missing)
            checks.append(Check(name, "warn", f"needs {needs}"))
        else:
            checks.append(Check(name, "pass", "via " + ", ".join(dict.fromkeys(via))))
    return checks
