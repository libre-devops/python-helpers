"""PIM for Azure resources, through Azure Resource Manager.

Access rests on Azure RBAC, so the Azure CLI's token works; the tenant needs Microsoft
Entra ID P2 or ID Governance. "Mine" views are asked at the root scope with ARM's own
filters (``asTarget()``, ``asRequestor()``, ``asApprover()``); a named principal is asked
per subscription with ``assignedTo()``, which includes roles held through a group and
those inherited from above.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import LdoError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.util import is_guid, odata_string, parse_datetime
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.pim.models import PimAssignment, PimRequest, PimSettings
from libre_devops_helpers.microsoft.pim.rules import settings_from_rules

PIM_API = "2020-10-01"
ROLES_API = "2022-04-01"
_AUTHZ = "providers/Microsoft.Authorization"


class AzurePimClient:
    """PIM for Azure resources. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        arm_url: str = PUBLIC.arm_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> AzurePimClient:
        api = ApiClient(
            arm_url,
            token_source(tokens, arm_url.rstrip("/") + "/", tenant_id),
            name="Azure PIM",
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
    ) -> AzurePimClient:
        return cls.create(
            tokens, profile.tenant_id, arm_url=profile.cloud.arm_url, verify=verify, session=session
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

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
        properties = items[0].get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
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
    properties = _map(item.get("properties"))
    expanded = _map(properties.get("expandedProperties"))
    principal = _map(expanded.get("principal"))
    role = _map(expanded.get("roleDefinition"))
    scope = _map(expanded.get("scope"))
    return PimAssignment(
        area="azure",
        state="eligible" if state == "eligible" else "active",
        role=str(role.get("displayName") or properties.get("roleDefinitionId") or ""),
        scope=str(scope.get("displayName") or properties.get("scope") or ""),
        principal_id=str(properties.get("principalId") or ""),
        principal_name=str(principal.get("displayName") or principal.get("email") or ""),
        member_type=str(properties.get("memberType") or ""),
        assignment_type=str(properties.get("assignmentType") or ""),
        starts=parse_datetime(properties.get("startDateTime")),
        ends=parse_datetime(properties.get("endDateTime")),
        raw=dict(item),
    )


def _request(item: Mapping[str, Any]) -> PimRequest:
    properties = _map(item.get("properties"))
    expanded = _map(properties.get("expandedProperties"))
    schedule = _map(properties.get("scheduleInfo"))
    expiration = _map(schedule.get("expiration"))
    ticket = _map(properties.get("ticketInfo"))
    return PimRequest(
        area="azure",
        id=str(item.get("id") or ""),
        action=str(properties.get("requestType") or ""),
        status=str(properties.get("status") or ""),
        role=str(_map(expanded.get("roleDefinition")).get("displayName") or ""),
        scope=str(_map(expanded.get("scope")).get("displayName") or properties.get("scope") or ""),
        principal_id=str(properties.get("principalId") or ""),
        principal_name=str(_map(expanded.get("principal")).get("displayName") or ""),
        justification=str(properties.get("justification") or ""),
        created=parse_datetime(properties.get("createdOn")),
        starts=parse_datetime(schedule.get("startDateTime")),
        ends=parse_datetime(expiration.get("endDateTime")),
        duration=str(expiration.get("duration") or ""),
        ticket=str(ticket.get("ticketNumber") or ""),
        raw=dict(item),
    )


def _map(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _guid(value: str) -> str:
    if not is_guid(value):
        raise LdoError(f"not an object id: {value!r}")
    return value.strip().lower()


def _scope(value: str) -> str:
    """An ARM scope, checked: '/subscriptions/<id>...' or a management group."""
    scope = "/" + value.strip().strip("/")
    if not (
        scope.startswith("/subscriptions/") or scope.startswith("/providers/Microsoft.Management/")
    ):
        raise LdoError(
            f"not an Azure scope: {value!r}",
            hint="use /subscriptions/<id>[/resourceGroups/<name>...] or a management group",
        )
    if ".." in scope or "://" in scope:
        raise LdoError(f"not an Azure scope: {value!r}")
    return scope


def _scopes(values: Iterable[str]) -> list[str]:
    scopes = [_scope(value) for value in values]
    if not scopes:
        raise LdoError("a named principal needs at least one scope to search")
    return scopes
