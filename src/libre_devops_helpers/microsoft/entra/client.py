"""Read-only Entra ID queries through Microsoft Graph v1.0.

Devices, users, groups and their memberships, directory roles, sign-ins, app
registration credentials and Conditional Access policies.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from operator import attrgetter
from typing import Any, Literal, TypeVar
from urllib.parse import quote

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import (
    AmbiguousError,
    ApiError,
    NotFoundError,
)
from libre_devops_helpers.core.sorting import sort_records
from libre_devops_helpers.core.util import (
    candidate_names,
    is_guid,
    odata_datetime,
    odata_string,
    require_guid,
)
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.entra.models import (
    AppCredential,
    ConditionalAccessPolicy,
    DeviceLookup,
    DirectoryObject,
    EntraDevice,
    EntraGroup,
    EntraUser,
    RoleAssignment,
    RoleReport,
    SignIn,
)

# An OData cast on a directory relationship (".../microsoft.graph.group") is an
# advanced query: Graph requires ConsistencyLevel: eventual together with $count=true.
_EVENTUAL = {"ConsistencyLevel": "eventual"}
_CREDENTIAL_SELECT = "id,appId,displayName,passwordCredentials,keyCredentials"
_CREDENTIAL_KINDS: tuple[tuple[str, Literal["secret", "certificate"]], ...] = (
    ("passwordCredentials", "secret"),
    ("keyCredentials", "certificate"),
)

T = TypeVar("T")

MemberKind = Literal["user", "device", "group", "servicePrincipal"]


class EntraClient(GraphServiceClient):
    """Entra ID lookups. Close it (or use ``with``) when done."""

    # Devices ----------------------------------------------------------------------

    def find_devices(self, name: str) -> list[EntraDevice]:
        """Devices whose display name is ``name``, else its short hostname, the most
        recently signed in first.

        Several results are normal: stale registrations keep the same name.
        """
        for candidate in candidate_names(name):
            devices = self._devices_matching(f"displayName eq {odata_string(candidate)}")
            if devices:
                return devices
        # A short name, where Entra holds the FQDN: its first label, exactly.
        short = name.strip().rstrip(".")
        if short and "." not in short:
            return [
                device
                for device in self._devices_matching(
                    f"startswith(displayName,{odata_string(short + '.')})"
                )
                if device.display_name.split(".", 1)[0].casefold() == short.casefold()
            ]
        return []

    def _devices_matching(self, query: str) -> list[EntraDevice]:
        """Devices the filter matches, the most recently signed in first."""
        devices = [
            EntraDevice.from_json(item)
            for item in self.api.get_all(
                "/v1.0/devices", params={"$filter": query, "$select": EntraDevice.SELECT}
            )
        ]
        return sort_records(devices, (attrgetter("last_sign_in"), True))

    def device_groups(
        self, device: EntraDevice | str, *, transitive: bool = True
    ) -> list[EntraGroup]:
        """Groups a device belongs to, including nested ones unless ``transitive=False``."""
        return self._groups_of("devices", _object_id(device), transitive)

    def look_up_devices(
        self,
        names: Sequence[str],
        groups: Sequence[EntraGroup] = (),
        *,
        transitive: bool = True,
        workers: int = 8,
    ) -> list[DeviceLookup]:
        """Each name's devices, as ``find_devices`` finds them, and their membership of
        ``groups`` (nested too, unless ``transitive=False``), in the order asked.

        Each group's members are fetched once, and the first name is looked up here on
        the calling thread, so a lapsed sign-in is met where someone can answer it; the
        rest are looked up ``workers`` at a time.
        """
        members = {
            group.id: frozenset(
                device.id for device in self.group_devices(group, transitive=transitive)
            )
            for group in groups
        }
        if not names:
            return []
        first = self.find_devices(names[0])
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rest = list(pool.map(self.find_devices, names[1:]))
        return [
            DeviceLookup(name, tuple(found), tuple(groups), members)
            for name, found in zip(names, [first, *rest], strict=True)
        ]

    def group_devices(
        self, group: EntraGroup | str, *, transitive: bool = True
    ) -> list[EntraDevice]:
        """Device members of a group, including nested groups unless ``transitive=False``."""
        relation = "transitiveMembers" if transitive else "members"
        items = self.api.get_all(
            f"/v1.0/groups/{_object_id(group)}/{relation}/microsoft.graph.device",
            params={"$select": EntraDevice.SELECT, "$count": "true", "$top": "999"},
            headers=_EVENTUAL,
        )
        devices = [EntraDevice.from_json(item) for item in items]
        return sorted(devices, key=lambda device: device.display_name.casefold())

    # Groups -----------------------------------------------------------------------

    def get_group(self, ref: str) -> EntraGroup:
        """One group, by object id or by exact display name.

        Raises NotFoundError when nothing matches and AmbiguousError when a display name
        is shared, since acting on the wrong group is worse than asking for its id.
        """
        ref = ref.strip()
        if is_guid(ref):
            data = self._get_one(
                f"/v1.0/groups/{ref}", EntraGroup.SELECT, f"no Entra group has id {ref}"
            )
            return EntraGroup.from_json(data)
        groups = [
            EntraGroup.from_json(item)
            for item in self._named("/v1.0/groups", ref, EntraGroup.SELECT)
        ]
        return _one(groups, ref, "Entra group", "Entra groups")

    def group_members(
        self,
        group: EntraGroup | str,
        *,
        transitive: bool = True,
        kind: MemberKind | None = None,
    ) -> list[DirectoryObject]:
        """Members of a group of any type, or of one ``kind`` only."""
        relation = "transitiveMembers" if transitive else "members"
        path = f"/v1.0/groups/{_object_id(group)}/{relation}"
        if kind is None:
            items: Iterable[dict[str, Any]] = self.api.get_all(path, params={"$top": "999"})
        else:
            items = self.api.get_all(
                f"{path}/microsoft.graph.{kind}",
                params={"$count": "true", "$top": "999"},
                headers=_EVENTUAL,
            )
        members = [DirectoryObject.from_json(item, kind) for item in items]
        return sorted(members, key=lambda member: (member.kind, member.display_name.casefold()))

    # Users and principals ---------------------------------------------------------

    def get_user(self, ref: str) -> EntraUser:
        """One user, by object id, by user principal name, or by exact display name."""
        ref = ref.strip()
        if is_guid(ref) or "@" in ref:
            # A guest UPN holds '#', so the segment must be percent-encoded.
            data = self._get_one(
                f"/v1.0/users/{quote(ref, safe='@')}",
                EntraUser.SELECT,
                f"no Entra user is {ref!r}",
            )
            return EntraUser.from_json(data)
        users = [
            EntraUser.from_json(item) for item in self._named("/v1.0/users", ref, EntraUser.SELECT)
        ]
        return _one(users, ref, "Entra user", "Entra users")

    def user_groups(self, user: EntraUser | str, *, transitive: bool = True) -> list[EntraGroup]:
        """Groups a user belongs to, including nested ones unless ``transitive=False``."""
        return self._groups_of("users", _object_id(user), transitive)

    def find_principal(self, ref: str) -> DirectoryObject:
        """A user, group or service principal, by object id, UPN or exact display name.

        Used to turn a name into the object id Azure role assignments are keyed on.
        """
        ref = ref.strip()
        if is_guid(ref):
            data = self._get_one(
                f"/v1.0/directoryObjects/{ref}", None, f"no Entra object has id {ref}"
            )
            return DirectoryObject.from_json(data)
        if "@" in ref:
            return DirectoryObject.from_json(self.get_user(ref).raw, "user")
        found = [
            DirectoryObject.from_json(item, kind)
            for path, kind in (
                ("/v1.0/groups", "group"),
                ("/v1.0/servicePrincipals", "servicePrincipal"),
                ("/v1.0/users", "user"),
            )
            for item in self._named(path, ref, "id,displayName,appId,userPrincipalName")
        ]
        return _one(found, ref, "Entra user, group or service principal", "Entra objects")

    # Roles ------------------------------------------------------------------------

    def user_roles(self, user: EntraUser | str) -> RoleReport:
        """Directory roles a user holds now, and those PIM makes them eligible for.

        Active roles include ones held through a role-assignable group. Eligibility
        needs PIM (Entra ID P2) and the right to read it; when it cannot be read, the
        report says why instead of failing.
        """
        user_id = _object_id(user)
        active = [
            RoleAssignment.from_directory_role(item)
            for item in self.api.get_all(
                f"/v1.0/users/{user_id}/transitiveMemberOf/microsoft.graph.directoryRole",
                params={"$count": "true"},
                headers=_EVENTUAL,
            )
        ]
        try:
            eligible: list[RoleAssignment] | None = [
                RoleAssignment.from_eligibility(item)
                for item in self.api.get_all(
                    "/v1.0/roleManagement/directory/roleEligibilitySchedules",
                    params={
                        "$filter": f"principalId eq {odata_string(user_id)}",
                        "$expand": "roleDefinition",
                    },
                )
            ]
            error = None
        except ApiError as exc:
            if exc.status not in {400, 403}:
                raise
            eligible, error = None, str(exc)
        return RoleReport(
            active=tuple(sorted(active, key=lambda role: role.role_name.casefold())),
            eligible=tuple(sorted(eligible, key=lambda role: role.role_name.casefold()))
            if eligible is not None
            else None,
            eligible_error=error,
        )

    # Sign-ins ---------------------------------------------------------------------

    def sign_ins(
        self,
        *,
        user: str | None = None,
        since: datetime | None = None,
        failures_only: bool = False,
        limit: int = 50,
    ) -> list[SignIn]:
        """Recent sign-ins, newest first. Needs Entra ID P1 in the tenant."""
        filters: list[str] = []
        if user:
            if is_guid(user):
                filters.append(f"userId eq {odata_string(user.strip())}")
            else:
                filters.append(f"userPrincipalName eq {odata_string(user.strip())}")
        if since is not None:
            filters.append(f"createdDateTime ge {odata_datetime(since)}")
        if failures_only:
            filters.append("status/errorCode ne 0")
        params = {"$top": str(max(1, min(limit, 999)))}
        if filters:
            params["$filter"] = " and ".join(filters)
        items = self.api.get_all("/v1.0/auditLogs/signIns", params=params)
        return [SignIn.from_json(item) for item in itertools.islice(items, limit)]

    # App credentials --------------------------------------------------------------

    def app_credentials(self, *, include_service_principals: bool = False) -> list[AppCredential]:
        """Every secret and certificate on app registrations (and service principals)."""
        sources: list[tuple[str, Literal["application", "service principal"]]] = [
            ("/v1.0/applications", "application")
        ]
        if include_service_principals:
            sources.append(("/v1.0/servicePrincipals", "service principal"))
        found: list[AppCredential] = []
        for path, owner_kind in sources:
            for item in self.api.get_all(
                path, params={"$select": _CREDENTIAL_SELECT, "$top": "999"}
            ):
                found.extend(_credentials(item, owner_kind))
        return found

    # Conditional Access -----------------------------------------------------------

    def ca_policies(self) -> list[ConditionalAccessPolicy]:
        """Every Conditional Access policy, sorted by name."""
        policies = [
            ConditionalAccessPolicy.from_json(item)
            for item in self.api.get_all("/v1.0/identity/conditionalAccess/policies")
        ]
        return sorted(policies, key=lambda policy: policy.display_name.casefold())

    # Helpers ----------------------------------------------------------------------

    def _groups_of(self, collection: str, object_id: str, transitive: bool) -> list[EntraGroup]:
        relation = "transitiveMemberOf" if transitive else "memberOf"
        items = self.api.get_all(
            f"/v1.0/{collection}/{object_id}/{relation}/microsoft.graph.group",
            params={"$select": EntraGroup.SELECT, "$count": "true", "$top": "999"},
            headers=_EVENTUAL,
        )
        groups = [EntraGroup.from_json(item) for item in items]
        return sorted(groups, key=lambda group: group.display_name.casefold())

    def _named(self, path: str, name: str, select: str) -> Iterator[dict[str, Any]]:
        return self.api.get_all(
            path, params={"$filter": f"displayName eq {odata_string(name)}", "$select": select}
        )

    def _get_one(self, path: str, select: str | None, missing: str) -> dict[str, Any]:
        try:
            return self.api.get(path, params={"$select": select} if select else None)
        except ApiError as exc:
            if exc.status == 404:
                raise NotFoundError(missing) from None
            raise


def expiring(
    credentials: Iterable[AppCredential],
    within: timedelta,
    *,
    now: datetime,
    include_expired: bool = True,
) -> list[AppCredential]:
    """Credentials that end within ``within`` of ``now`` (and expired ones), soonest first."""
    selected = [
        credential
        for credential in credentials
        if credential.ends is not None
        and credential.ends - now <= within
        and (include_expired or credential.ends >= now)
    ]
    return sorted(selected, key=lambda credential: credential.ends or now)


def _credentials(
    item: dict[str, Any], owner_kind: Literal["application", "service principal"]
) -> list[AppCredential]:
    found: list[AppCredential] = []
    for key, kind in _CREDENTIAL_KINDS:
        entries = item.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            found.append(
                AppCredential(
                    owner_kind=owner_kind,
                    owner_name=fields.text(item, "displayName"),
                    owner_id=fields.text(item, "id"),
                    app_id=fields.text(item, "appId"),
                    kind=kind,
                    name=(fields.text(entry, "displayName") or fields.text(entry, "hint")),
                    key_id=fields.text(entry, "keyId"),
                    starts=fields.when(entry, "startDateTime"),
                    ends=fields.when(entry, "endDateTime"),
                    raw=dict(entry),
                )
            )
    return found


def _one(items: list[T], ref: str, singular: str, plural: str) -> T:
    if not items:
        raise NotFoundError(f"no {singular} is named {ref!r}")
    if len(items) > 1:
        ids = ", ".join(str(getattr(item, "id", "")) for item in items)
        raise AmbiguousError(
            f"{len(items)} {plural} are named {ref!r}: {ids}", hint="pass the object id instead"
        )
    return items[0]


def _object_id(value: EntraDevice | EntraGroup | EntraUser | DirectoryObject | str) -> str:
    return require_guid(value if isinstance(value, str) else value.id, "an Entra object id")
