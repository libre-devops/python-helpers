"""Entra ID objects as returned by Microsoft Graph, trimmed to the fields used here.

Every model keeps the full Graph record in ``raw`` for JSON output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from libre_devops_helpers.core import fields


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
        """A device as Graph returns it."""
        return cls(
            id=fields.text(data, "id"),
            display_name=fields.text(data, "displayName"),
            device_id=fields.text(data, "deviceId"),
            operating_system=fields.text(data, "operatingSystem"),
            os_version=fields.text(data, "operatingSystemVersion"),
            enabled=fields.flag(data.get("accountEnabled")),
            trust_type=fields.text(data, "trustType"),
            last_sign_in=fields.when(data, "approximateLastSignInDateTime"),
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
        """A group as Graph returns it; ``dynamic`` from its group types."""
        group_types = data.get("groupTypes")
        return cls(
            id=fields.text(data, "id"),
            display_name=fields.text(data, "displayName"),
            description=fields.text(data, "description"),
            dynamic=isinstance(group_types, list) and "DynamicMembership" in group_types,
            security_enabled=fields.flag(data.get("securityEnabled")),
            membership_rule=fields.text(data, "membershipRule"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class DeviceLookup:
    """One device name looked up: the Entra devices that have it (stale registrations share
    names, so there may be several), and which of the ``groups`` asked about they are in."""

    query: str
    devices: tuple[EntraDevice, ...]
    groups: tuple[EntraGroup, ...] = ()
    # Each group's id, and the object ids of every device in it.
    members: Mapping[str, frozenset[str]] = field(default_factory=dict, repr=False)

    @property
    def found(self) -> bool:
        """Whether Entra has any device with the name."""
        return bool(self.devices)

    def in_group(self, group: EntraGroup, device: EntraDevice | None = None) -> bool:
        """Whether ``device``, or else any device with the name, is a member of ``group``."""
        ids = self.members.get(group.id, frozenset())
        return any(item.id in ids for item in ((device,) if device else self.devices))

    @property
    def in_every_group(self) -> bool:
        """Whether a device with the name is in every group asked about."""
        return all(self.in_group(group) for group in self.groups)


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
        """A user as Graph returns it."""
        return cls(
            id=fields.text(data, "id"),
            display_name=fields.text(data, "displayName"),
            user_principal_name=fields.text(data, "userPrincipalName"),
            mail=fields.text(data, "mail"),
            enabled=fields.flag(data.get("accountEnabled")),
            user_type=fields.text(data, "userType"),
            synced=fields.flag(data.get("onPremisesSyncEnabled")),
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
        """Any directory object, its kind from ``@odata.type`` unless ``kind`` says; the detail is
        what best tells one apart (a UPN, an OS, an app id)."""
        odata_type = fields.text(data, "@odata.type").removeprefix("#microsoft.graph.")
        kind = kind or odata_type or "object"
        detail = {
            "user": fields.text(data, "userPrincipalName"),
            "device": fields.text(data, "operatingSystem"),
            "servicePrincipal": fields.text(data, "appId"),
        }.get(kind, "")
        return cls(
            id=fields.text(data, "id"),
            kind=kind,
            display_name=fields.text(data, "displayName"),
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
            role_name=fields.text(data, "displayName"),
            role_template_id=fields.text(data, "roleTemplateId"),
            state="active",
            scope="/",
            ends=None,
            raw=dict(data),
        )

    @classmethod
    def from_eligibility(cls, data: Mapping[str, Any]) -> RoleAssignment:
        """From a PIM ``unifiedRoleEligibilitySchedule`` expanded with its role definition."""
        definition = fields.mapping(data.get("roleDefinition"))
        expiration = fields.mapping(fields.mapping(data.get("scheduleInfo")).get("expiration"))
        role_id = fields.text(data, "roleDefinitionId")
        return cls(
            role_name=fields.text(definition, "displayName") or role_id,
            role_template_id=fields.text(definition, "templateId") or role_id,
            state="eligible",
            scope=fields.text(data, "directoryScopeId") or "/",
            ends=fields.when(expiration, "endDateTime"),
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
        """Whether the sign-in succeeded (error code 0)."""
        return self.error_code == 0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SignIn:
        """A sign-in log entry as Graph returns it."""
        status = fields.mapping(data.get("status"))
        device = fields.mapping(data.get("deviceDetail"))
        location = fields.mapping(data.get("location"))
        code = status.get("errorCode")
        city, country = fields.text(location, "city"), fields.text(location, "countryOrRegion")
        place = ", ".join(part for part in (city, country) if part)
        return cls(
            id=fields.text(data, "id"),
            created=fields.when(data, "createdDateTime"),
            user=fields.text(data, "userPrincipalName"),
            app=fields.text(data, "appDisplayName"),
            ip_address=fields.text(data, "ipAddress"),
            client_app=fields.text(data, "clientAppUsed"),
            conditional_access=fields.text(data, "conditionalAccessStatus"),
            error_code=code if isinstance(code, int) and not isinstance(code, bool) else 0,
            failure_reason=fields.text(status, "failureReason"),
            device_name=fields.text(device, "displayName"),
            operating_system=fields.text(device, "operatingSystem"),
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
        """A Conditional Access policy as Graph returns it, conditions and controls flattened."""
        conditions = fields.mapping(data.get("conditions"))
        users = fields.mapping(conditions.get("users"))
        apps = fields.mapping(conditions.get("applications"))
        grant = fields.mapping(data.get("grantControls"))
        session = fields.mapping(data.get("sessionControls"))
        return cls(
            id=fields.text(data, "id"),
            display_name=fields.text(data, "displayName"),
            state=fields.text(data, "state"),
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
            grant_operator=fields.text(grant, "operator"),
            session_controls=tuple(
                name for name, value in session.items() if value and name != "@odata.type"
            ),
            modified=(
                fields.when(data, "modifiedDateTime") or fields.when(data, "createdDateTime")
            ),
            raw=dict(data),
        )
