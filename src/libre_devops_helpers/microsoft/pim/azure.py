"""PIM for Azure resources, through Azure Resource Manager.

Access rests on Azure RBAC, so the Azure CLI's token works; the tenant needs Microsoft
Entra ID P2 or ID Governance. "Mine" views are asked at the root scope with ARM's own
filters (``asTarget()``, ``asRequestor()``, ``asApprover()``); a named principal is asked
per subscription with ``assignedTo()``, which includes roles held through a group and
those inherited from above.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import InputError, NotFoundError
from libre_devops_helpers.core.util import odata_string, require_guid
from libre_devops_helpers.microsoft.api_clients import ArmServiceClient
from libre_devops_helpers.microsoft.pim.models import PimAssignment, PimRequest, PimSettings
from libre_devops_helpers.microsoft.pim.rules import settings_from_rules

PIM_API = "2020-10-01"
ROLES_API = "2022-04-01"
_AUTHZ = "providers/Microsoft.Authorization"


class AzurePimClient(ArmServiceClient):
    """PIM for Azure resources. Close it (or use ``with``) when done."""

    API_NAME = "Azure PIM"

    def eligible(
        self, *, principal_id: str | None = None, scopes: Iterable[str] = ()
    ) -> list[PimAssignment]:
        """Eligible role assignments: the signed-in user's, or ``principal_id``'s."""
        return self._instances("roleEligibilityScheduleInstances", "eligible", principal_id, scopes)

    def active(
        self, *, principal_id: str | None = None, scopes: Iterable[str] = ()
    ) -> list[PimAssignment]:
        """Active role assignments, activated through PIM or standing."""
        return self._instances("roleAssignmentScheduleInstances", "active", principal_id, scopes)

    def requests(
        self, *, approver: bool = False, principal_id: str | None = None, scopes: Iterable[str] = ()
    ) -> list[PimRequest]:
        """Requests the signed-in user made, or ones waiting on them with ``approver``."""
        if principal_id:
            pairs = [
                (scope, f"principalId eq {odata_string(_guid(principal_id))}")
                for scope in _scopes(scopes)
            ]
        else:
            pairs = [("", "asApprover()" if approver else "asRequestor()")]
        found: dict[str, PimRequest] = {}
        for scope, expression in pairs:
            for item in self._list(scope, "roleAssignmentScheduleRequests", expression):
                request = _request(item)
                found.setdefault(request.id, request)
        return sorted(found.values(), key=lambda item: str(item.created or ""), reverse=True)

    def settings(self, role: str, scope: str) -> PimSettings:
        """A role's PIM settings at ``scope`` (a subscription, resource group or resource)."""
        scope = _scope(scope)
        definitions = list(
            self.api.get_all(
                f"{scope}/{_AUTHZ}/roleDefinitions",
                params={"api-version": ROLES_API, "$filter": f"roleName eq {odata_string(role)}"},
                next_link="nextLink",
            )
        )
        if not definitions:
            raise NotFoundError(f"no Azure role is named {role!r} at {scope}")
        definition_id = str(definitions[0].get("id") or "")
        items = list(
            self.api.get_all(
                f"{scope}/{_AUTHZ}/roleManagementPolicyAssignments",
                params={
                    "api-version": PIM_API,
                    "$filter": f"roleDefinitionId eq {odata_string(definition_id)}",
                },
                next_link="nextLink",
            )
        )
        if not items:
            raise NotFoundError(f"no PIM settings for {role!r} at {scope}")
        properties = fields.mapping(items[0].get("properties"))
        rules = properties.get("effectiveRules") or []
        return settings_from_rules("azure", role, scope, rules if isinstance(rules, list) else [])

    def _instances(
        self, collection: str, state: str, principal_id: str | None, scopes: Iterable[str]
    ) -> list[PimAssignment]:
        if principal_id:
            expression = f"assignedTo({odata_string(_guid(principal_id))})"
            pairs = [(scope, expression) for scope in _scopes(scopes)]
        else:
            pairs = [("", "asTarget()")]
        found: dict[str, PimAssignment] = {}
        for scope, expression in pairs:
            for item in self._list(scope, collection, expression):
                assignment = _assignment(item, state)
                found.setdefault(str(item.get("id") or id(item)), assignment)
        return sorted(found.values(), key=lambda item: (item.role.casefold(), item.scope))

    def _list(self, scope: str, collection: str, expression: str) -> list[dict[str, Any]]:
        return list(
            self.api.get_all(
                f"{scope}/{_AUTHZ}/{collection}",
                params={"api-version": PIM_API, "$filter": expression},
                next_link="nextLink",
            )
        )


def _assignment(item: Mapping[str, Any], state: str) -> PimAssignment:
    properties = fields.mapping(item.get("properties"))
    expanded = fields.mapping(properties.get("expandedProperties"))
    principal = fields.mapping(expanded.get("principal"))
    role = fields.mapping(expanded.get("roleDefinition"))
    scope = fields.mapping(expanded.get("scope"))
    return PimAssignment(
        area="azure",
        state="eligible" if state == "eligible" else "active",
        role=fields.text(role, "displayName") or fields.text(properties, "roleDefinitionId"),
        scope=fields.text(scope, "displayName") or fields.text(properties, "scope"),
        principal_id=fields.text(properties, "principalId"),
        principal_name=fields.text(principal, "displayName") or fields.text(principal, "email"),
        member_type=fields.text(properties, "memberType"),
        assignment_type=fields.text(properties, "assignmentType"),
        starts=fields.when(properties, "startDateTime"),
        ends=fields.when(properties, "endDateTime"),
        raw=dict(item),
    )


def _request(item: Mapping[str, Any]) -> PimRequest:
    properties = fields.mapping(item.get("properties"))
    expanded = fields.mapping(properties.get("expandedProperties"))
    role = fields.mapping(expanded.get("roleDefinition"))
    scope = fields.mapping(expanded.get("scope"))
    principal = fields.mapping(expanded.get("principal"))
    schedule = fields.mapping(properties.get("scheduleInfo"))
    expiration = fields.mapping(schedule.get("expiration"))
    ticket = fields.mapping(properties.get("ticketInfo"))
    return PimRequest(
        area="azure",
        id=fields.text(item, "id"),
        action=fields.text(properties, "requestType"),
        status=fields.text(properties, "status"),
        role=fields.text(role, "displayName"),
        scope=fields.text(scope, "displayName") or fields.text(properties, "scope"),
        principal_id=fields.text(properties, "principalId"),
        principal_name=fields.text(principal, "displayName"),
        justification=fields.text(properties, "justification"),
        created=fields.when(properties, "createdOn"),
        starts=fields.when(schedule, "startDateTime"),
        ends=fields.when(expiration, "endDateTime"),
        duration=fields.text(expiration, "duration"),
        ticket=fields.text(ticket, "ticketNumber"),
        raw=dict(item),
    )


def _guid(value: str) -> str:
    return require_guid(value, "an object id")


def _scope(value: str) -> str:
    """An ARM scope, checked: '/subscriptions/<id>...' or a management group."""
    scope = "/" + value.strip().strip("/")
    if not (
        scope.startswith("/subscriptions/") or scope.startswith("/providers/Microsoft.Management/")
    ):
        raise InputError(
            f"not an Azure scope: {value!r}",
            hint="use /subscriptions/<id>[/resourceGroups/<name>...] or a management group",
        )
    if ".." in scope or "://" in scope:
        raise InputError(f"not an Azure scope: {value!r}")
    return scope


def _scopes(values: Iterable[str]) -> list[str]:
    scopes = [_scope(value) for value in values]
    if not scopes:
        raise InputError("a named principal needs at least one scope to search")
    return scopes
