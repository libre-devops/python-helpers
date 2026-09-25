"""PIM for Entra roles and for groups, through Microsoft Graph v1.0.

"Mine" views use Graph's ``filterByCurrentUser``, so they need a delegated token (the
Azure CLI's does not carry the scopes; a profile with ``auth = "interactive"`` or
``"device-code"`` does). A named principal is asked with a ``principalId`` filter, which
an app registration's application permissions can serve. Graph asks for a ReadWrite
scope even to list requests; this module still only ever reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import ApiError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.util import is_guid, odata_string, require_guid
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.pim.models import (
    Area,
    PimAssignment,
    PimRequest,
    PimSettings,
)
from libre_devops_helpers.microsoft.pim.rules import settings_from_rules

_ROLES = "/v1.0/roleManagement/directory"
_GROUPS = "/v1.0/identityGovernance/privilegedAccess/group"


class GraphPimClient(GraphServiceClient):
    """PIM for Entra roles and PIM for Groups. Close it (or use ``with``) when done."""

    API_NAME = "Graph PIM"

    def __init__(self, api: ApiClient) -> None:
        super().__init__(api)
        self._role_names: dict[str, str] | None = None
        self._group_names: dict[str, str] = {}

    # Entra roles --------------------------------------------------------------------

    def role_eligible(self, *, principal_id: str | None = None) -> list[PimAssignment]:
        """Entra roles the signed-in user (or ``principal_id``) may activate."""
        items = self._mine_or_theirs(f"{_ROLES}/roleEligibilityScheduleInstances", principal_id)
        return self._role_assignments(items, "eligible")

    def role_active(self, *, principal_id: str | None = None) -> list[PimAssignment]:
        """Entra roles the signed-in user (or ``principal_id``) holds now, assigned or activated."""
        items = self._mine_or_theirs(f"{_ROLES}/roleAssignmentScheduleInstances", principal_id)
        return self._role_assignments(items, "active")

    def role_requests(
        self, *, approver: bool = False, principal_id: str | None = None
    ) -> list[PimRequest]:
        """Role requests the signed-in user (or ``principal_id``) made, or with ``approver`` those
        waiting on them; the newest first."""
        path = f"{_ROLES}/roleAssignmentScheduleRequests"
        items = self._mine_or_theirs(path, principal_id, on="approver" if approver else "principal")
        names = self.role_names()
        return _newest([_request("entra", item, names) for item in items])

    def role_settings(self, role: str) -> PimSettings:
        """An Entra role's PIM settings, for the whole directory."""
        role_id = self._role_id(role)
        assignments = list(
            self.api.get_all(
                "/v1.0/policies/roleManagementPolicyAssignments",
                params={
                    "$filter": "scopeId eq '/' and scopeType eq 'DirectoryRole' "
                    f"and roleDefinitionId eq {odata_string(role_id)}",
                    "$expand": "policy($expand=rules)",
                },
            )
        )
        if not assignments:
            raise NotFoundError(f"no PIM settings for the Entra role {role!r}")
        return settings_from_rules(
            "entra", self.role_names().get(role_id, role), "/", _rules(assignments[0])
        )

    def role_names(self) -> dict[str, str]:
        """Every directory role definition's name by id, fetched once."""
        if self._role_names is None:
            self._role_names = {
                fields.text(item, "id"): fields.text(item, "displayName")
                for item in self.api.get_all(
                    f"{_ROLES}/roleDefinitions", params={"$select": "id,displayName"}
                )
            }
        return self._role_names

    # PIM for Groups -----------------------------------------------------------------

    def group_eligible(self, *, principal_id: str | None = None) -> list[PimAssignment]:
        """Group memberships and ownerships the signed-in user (or ``principal_id``) could
        activate."""
        items = self._mine_or_theirs(f"{_GROUPS}/eligibilityScheduleInstances", principal_id)
        return self._group_assignments(items, "eligible")

    def group_active(self, *, principal_id: str | None = None) -> list[PimAssignment]:
        """Group memberships and ownerships the signed-in user (or ``principal_id``) holds now."""
        items = self._mine_or_theirs(f"{_GROUPS}/assignmentScheduleInstances", principal_id)
        return self._group_assignments(items, "active")

    def group_requests(
        self, *, approver: bool = False, principal_id: str | None = None
    ) -> list[PimRequest]:
        """Group requests the signed-in user (or ``principal_id``) made, or with ``approver`` those
        waiting on them; the newest first."""
        path = f"{_GROUPS}/assignmentScheduleRequests"
        items = self._mine_or_theirs(path, principal_id, on="approver" if approver else "principal")
        return _newest([self._group_request(item) for item in items])

    def group_settings(self, group_id: str, access: str = "member") -> PimSettings:
        """A group's PIM settings for its members (``member``) or owners (``owner``)."""
        group_id = _guid(group_id)
        assignments = list(
            self.api.get_all(
                "/v1.0/policies/roleManagementPolicyAssignments",
                params={
                    "$filter": f"scopeId eq {odata_string(group_id)} and scopeType eq 'Group' "
                    f"and roleDefinitionId eq {odata_string(access)}",
                    "$expand": "policy($expand=rules)",
                },
            )
        )
        if not assignments:
            raise NotFoundError(f"no PIM settings for group {group_id} ({access})")
        return settings_from_rules(
            "groups", access, self.group_name(group_id), _rules(assignments[0])
        )

    def group_name(self, group_id: str) -> str:
        """A group's display name, cached; its id when the name cannot be read."""
        if not is_guid(group_id):
            # Never build a path from something that is not an object id.
            return group_id
        if group_id not in self._group_names:
            try:
                data = self.api.get(f"/v1.0/groups/{group_id}", params={"$select": "displayName"})
                self._group_names[group_id] = str(data.get("displayName") or group_id)
            except ApiError:
                self._group_names[group_id] = group_id
        return self._group_names[group_id]

    # Helpers ------------------------------------------------------------------------

    def _mine_or_theirs(
        self, path: str, principal_id: str | None, *, on: str = "principal"
    ) -> list[dict[str, Any]]:
        if principal_id:
            params = {"$filter": f"principalId eq {odata_string(_guid(principal_id))}"}
            return list(self.api.get_all(path, params=params))
        return list(self.api.get_all(f"{path}/filterByCurrentUser(on='{on}')"))

    def _role_id(self, role: str) -> str:
        if is_guid(role):
            return role.strip().lower()
        wanted = role.strip().casefold()
        for role_id, name in self.role_names().items():
            if name.casefold() == wanted:
                return role_id
        raise NotFoundError(f"no Entra role is named {role!r}")

    def _role_assignments(self, items: list[dict[str, Any]], state: str) -> list[PimAssignment]:
        names = self.role_names()
        found = [
            PimAssignment(
                area="entra",
                state="eligible" if state == "eligible" else "active",
                role=names.get(
                    fields.text(item, "roleDefinitionId"), fields.text(item, "roleDefinitionId")
                ),
                scope=str(item.get("directoryScopeId") or "/"),
                principal_id=fields.text(item, "principalId"),
                principal_name="",
                member_type=fields.text(item, "memberType"),
                assignment_type=fields.text(item, "assignmentType"),
                starts=fields.when(item, "startDateTime"),
                ends=fields.when(item, "endDateTime"),
                raw=dict(item),
            )
            for item in items
        ]
        return sorted(found, key=lambda item: item.role.casefold())

    def _group_assignments(self, items: list[dict[str, Any]], state: str) -> list[PimAssignment]:
        found = [
            PimAssignment(
                area="groups",
                state="eligible" if state == "eligible" else "active",
                role=fields.text(item, "accessId"),
                scope=self.group_name(fields.text(item, "groupId")),
                principal_id=fields.text(item, "principalId"),
                principal_name="",
                member_type=fields.text(item, "memberType"),
                assignment_type=fields.text(item, "assignmentType"),
                starts=fields.when(item, "startDateTime"),
                ends=fields.when(item, "endDateTime"),
                raw=dict(item),
            )
            for item in items
        ]
        return sorted(found, key=lambda item: (item.scope.casefold(), item.role))

    def _group_request(self, item: Mapping[str, Any]) -> PimRequest:
        return replace(
            _request("groups", item, {}),
            role=fields.text(item, "accessId"),
            scope=self.group_name(fields.text(item, "groupId")),
        )


def _request(area: Area, item: Mapping[str, Any], role_names: Mapping[str, str]) -> PimRequest:
    schedule = fields.mapping(item.get("scheduleInfo"))
    expiration = fields.mapping(schedule.get("expiration"))
    ticket = fields.mapping(item.get("ticketInfo"))
    role_id = fields.text(item, "roleDefinitionId")
    return PimRequest(
        area=area,
        id=fields.text(item, "id"),
        action=fields.text(item, "action"),
        status=fields.text(item, "status"),
        role=role_names.get(role_id, role_id),
        scope=str(item.get("directoryScopeId") or "/"),
        principal_id=fields.text(item, "principalId"),
        principal_name="",
        justification=fields.text(item, "justification"),
        created=fields.when(item, "createdDateTime"),
        starts=fields.when(schedule, "startDateTime"),
        ends=fields.when(expiration, "endDateTime"),
        duration=fields.text(expiration, "duration"),
        ticket=fields.text(ticket, "ticketNumber"),
        raw=dict(item),
    )


def _rules(assignment: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    policy = assignment.get("policy")
    rules = policy.get("rules") if isinstance(policy, Mapping) else None
    return [rule for rule in rules if isinstance(rule, Mapping)] if isinstance(rules, list) else []


def _newest(requests_: list[PimRequest]) -> list[PimRequest]:
    return sorted(requests_, key=lambda item: str(item.created or ""), reverse=True)


def _guid(value: str) -> str:
    return require_guid(value, "an object id")
