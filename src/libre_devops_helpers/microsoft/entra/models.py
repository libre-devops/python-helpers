"""Entra ID objects as returned by Microsoft Graph, trimmed to the fields used here.

Every model keeps the full Graph record in ``raw`` for JSON output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from libre_devops_helpers.core.util import parse_datetime


def _text(data: Mapping[str, Any], key: str) -> str:
    return str(data.get(key) or "")


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


@dataclass(frozen=True)
class EntraDevice:
    """An Entra device object."""

    SELECT: ClassVar[str] = (
        "id,displayName,deviceId,operatingSystem,operatingSystemVersion,"
        "accountEnabled,trustType,approximateLastSignInDateTime"
    )

    id: str
    display_name: str
    device_id: str
    operating_system: str
    os_version: str
    enabled: bool | None
    trust_type: str
    last_sign_in: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> EntraDevice:
        return cls(
            id=str(data.get("id", "")),
            display_name=_text(data, "displayName"),
            device_id=_text(data, "deviceId"),
            operating_system=_text(data, "operatingSystem"),
            os_version=_text(data, "operatingSystemVersion"),
            enabled=_bool(data.get("accountEnabled")),
            trust_type=_text(data, "trustType"),
            last_sign_in=parse_datetime(data.get("approximateLastSignInDateTime")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class EntraGroup:
    """An Entra group. ``dynamic`` is true for rule-based membership."""

    SELECT: ClassVar[str] = (
        "id,displayName,description,groupTypes,securityEnabled,mailEnabled,membershipRule"
    )

    id: str
    display_name: str
    description: str
    dynamic: bool
    security_enabled: bool | None
    membership_rule: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> EntraGroup:
        group_types = data.get("groupTypes")
        return cls(
            id=str(data.get("id", "")),
            display_name=_text(data, "displayName"),
            description=_text(data, "description"),
            dynamic=isinstance(group_types, list) and "DynamicMembership" in group_types,
            security_enabled=_bool(data.get("securityEnabled")),
            membership_rule=_text(data, "membershipRule"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class EntraUser:
    """An Entra user."""

    SELECT: ClassVar[str] = (
        "id,displayName,userPrincipalName,mail,accountEnabled,userType,onPremisesSyncEnabled"
    )

    id: str
    display_name: str
    user_principal_name: str
    mail: str
    enabled: bool | None
    user_type: str
    synced: bool | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> EntraUser:
        return cls(
            id=str(data.get("id", "")),
            display_name=_text(data, "displayName"),
            user_principal_name=_text(data, "userPrincipalName"),
            mail=_text(data, "mail"),
            enabled=_bool(data.get("accountEnabled")),
            user_type=_text(data, "userType"),
            synced=_bool(data.get("onPremisesSyncEnabled")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class DirectoryObject:
    """A group member of any type. ``kind`` is ``user``, ``device``, ``group``, ...

    ``detail`` is the most useful extra field for the kind: a user's UPN, a device's
    operating system, a service principal's app id.
    """

    id: str
    kind: str
    display_name: str
    detail: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], kind: str | None = None) -> DirectoryObject:
        odata_type = _text(data, "@odata.type").removeprefix("#microsoft.graph.")
        kind = kind or odata_type or "object"
        detail = {
            "user": _text(data, "userPrincipalName"),
            "device": _text(data, "operatingSystem"),
            "servicePrincipal": _text(data, "appId"),
        }.get(kind, "")
        return cls(
            id=str(data.get("id", "")),
            kind=kind,
            display_name=_text(data, "displayName"),
            detail=detail,
            raw=dict(data),
        )


@dataclass(frozen=True)
class RoleAssignment:
    """A directory role a principal holds: ``active`` now, or ``eligible`` through PIM."""

    role_name: str
    role_template_id: str
    state: Literal["active", "eligible"]
    scope: str
    ends: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_directory_role(cls, data: Mapping[str, Any]) -> RoleAssignment:
        """From a ``directoryRole`` the principal is a member of (tenant-wide, active)."""
        return cls(
            role_name=_text(data, "displayName"),
            role_template_id=_text(data, "roleTemplateId"),
            state="active",
            scope="/",
            ends=None,
            raw=dict(data),
        )

    @classmethod
    def from_eligibility(cls, data: Mapping[str, Any]) -> RoleAssignment:
        """From a PIM ``unifiedRoleEligibilitySchedule`` expanded with its role definition."""
        definition = data.get("roleDefinition")
        definition = definition if isinstance(definition, Mapping) else {}
        schedule = data.get("scheduleInfo")
        expiration = schedule.get("expiration") if isinstance(schedule, Mapping) else None
        ends = expiration.get("endDateTime") if isinstance(expiration, Mapping) else None
        return cls(
            role_name=_text(definition, "displayName") or _text(data, "roleDefinitionId"),
            role_template_id=_text(definition, "templateId") or _text(data, "roleDefinitionId"),
            state="eligible",
            scope=_text(data, "directoryScopeId") or "/",
            ends=parse_datetime(ends),
            raw=dict(data),
        )


@dataclass(frozen=True)
class RoleReport:
    """A principal's directory roles. ``eligible`` is None when PIM could not be read."""

    active: tuple[RoleAssignment, ...]
    eligible: tuple[RoleAssignment, ...] | None
    eligible_error: str | None = None


@dataclass(frozen=True)
class SignIn:
    """One Entra sign-in event. ``error_code`` 0 is a success."""

    id: str
    created: datetime | None
    user: str
    app: str
    ip_address: str
    client_app: str
    conditional_access: str
    error_code: int
    failure_reason: str
    device_name: str
    operating_system: str
    location: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def succeeded(self) -> bool:
        return self.error_code == 0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SignIn:
        status = data.get("status")
        status = status if isinstance(status, Mapping) else {}
        device = data.get("deviceDetail")
        device = device if isinstance(device, Mapping) else {}
        location = data.get("location")
        location = location if isinstance(location, Mapping) else {}
        code = status.get("errorCode")
        place = ", ".join(
            part for part in (_text(location, "city"), _text(location, "countryOrRegion")) if part
        )
        return cls(
            id=str(data.get("id", "")),
            created=parse_datetime(data.get("createdDateTime")),
            user=_text(data, "userPrincipalName"),
            app=_text(data, "appDisplayName"),
            ip_address=_text(data, "ipAddress"),
            client_app=_text(data, "clientAppUsed"),
            conditional_access=_text(data, "conditionalAccessStatus"),
            error_code=code if isinstance(code, int) and not isinstance(code, bool) else 0,
            failure_reason=_text(status, "failureReason"),
            device_name=_text(device, "displayName"),
            operating_system=_text(device, "operatingSystem"),
            location=place,
            raw=dict(data),
        )


@dataclass(frozen=True)
class AppCredential:
    """A client secret or certificate on an app registration or a service principal."""

    owner_kind: Literal["application", "service principal"]
    owner_name: str
    owner_id: str
    app_id: str
    kind: Literal["secret", "certificate"]
    name: str
    key_id: str
    starts: datetime | None
    ends: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def days_left(self, now: datetime) -> int | None:
        """Whole days until expiry (negative once expired), or None with no end date."""
        if self.ends is None:
            return None
        return (self.ends - now).days


@dataclass(frozen=True)
class ConditionalAccessPolicy:
    """A Conditional Access policy, flattened to who and what it targets and what it requires."""

    id: str
    display_name: str
    state: str
    include_users: tuple[str, ...]
    exclude_users: tuple[str, ...]
    include_groups: tuple[str, ...]
    exclude_groups: tuple[str, ...]
    include_roles: tuple[str, ...]
    include_applications: tuple[str, ...]
    exclude_applications: tuple[str, ...]
    client_app_types: tuple[str, ...]
    grant_controls: tuple[str, ...]
    grant_operator: str
    session_controls: tuple[str, ...]
    modified: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ConditionalAccessPolicy:
        conditions = data.get("conditions")
        conditions = conditions if isinstance(conditions, Mapping) else {}
        users = conditions.get("users")
        users = users if isinstance(users, Mapping) else {}
        apps = conditions.get("applications")
        apps = apps if isinstance(apps, Mapping) else {}
        grant = data.get("grantControls")
        grant = grant if isinstance(grant, Mapping) else {}
        session = data.get("sessionControls")
        session = session if isinstance(session, Mapping) else {}
        return cls(
            id=str(data.get("id", "")),
            display_name=_text(data, "displayName"),
            state=_text(data, "state"),
            include_users=_strings(users.get("includeUsers")),
            exclude_users=_strings(users.get("excludeUsers")),
            include_groups=_strings(users.get("includeGroups")),
            exclude_groups=_strings(users.get("excludeGroups")),
            include_roles=_strings(users.get("includeRoles")),
            include_applications=_strings(apps.get("includeApplications")),
            exclude_applications=_strings(apps.get("excludeApplications")),
            client_app_types=_strings(conditions.get("clientAppTypes")),
            grant_controls=(
                *_strings(grant.get("builtInControls")),
                *_strings(grant.get("customAuthenticationFactors")),
                *(("terms of use",) if grant.get("termsOfUse") else ()),
            ),
            grant_operator=_text(grant, "operator"),
            session_controls=tuple(
                name for name, value in session.items() if value and name != "@odata.type"
            ),
            modified=parse_datetime(data.get("modifiedDateTime") or data.get("createdDateTime")),
            raw=dict(data),
        )
