"""Read-only Azure Resource Manager queries.

Subscriptions, Azure Resource Graph, RBAC role assignments, and Defender for Cloud
(secure score, controls, recommendations, plans). Access rests on Azure RBAC (Reader is
enough for all of it), not on token scopes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import ApiError, LdoError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import is_guid
from libre_devops_helpers.microsoft.azure.models import (
    Assessment,
    AzureRoleAssignment,
    DefenderPlan,
    SecureScore,
    SecureScoreControl,
    Subscription,
)
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile

SUBSCRIPTIONS_API = "2022-12-01"
RESOURCE_GRAPH_API = "2022-10-01"
AUTHORIZATION_API = "2022-04-01"
SECURE_SCORE_API = "2020-01-01"
ASSESSMENTS_API = "2021-06-01"
PRICINGS_API = "2024-01-01"

# Resource Graph returns at most 1000 rows a page.
_GRAPH_PAGE = 1000


class AzureClient:
    """Azure Resource Manager lookups. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self._role_names: dict[str, str] = {}

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        arm_url: str = PUBLIC.arm_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> AzureClient:
        """A client for ``tenant_id`` that takes its ARM tokens from ``tokens``."""
        api = ApiClient(
            arm_url,
            token_source(tokens, arm_url.rstrip("/") + "/", tenant_id),
            name="Azure Resource Manager",
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
    ) -> AzureClient:
        """A client for a configured profile's tenant, in the profile's cloud."""
        return cls.create(
            tokens, profile.tenant_id, arm_url=profile.cloud.arm_url, verify=verify, session=session
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Subscriptions ----------------------------------------------------------------

    def subscriptions(self, tenant_id: str | None = None) -> list[Subscription]:
        """Subscriptions the credential can see, in ``tenant_id`` when given, by name."""
        items = self.api.get_all(
            "/subscriptions", params={"api-version": SUBSCRIPTIONS_API}, next_link="nextLink"
        )
        found = [Subscription.from_json(item) for item in items]
        if tenant_id is not None:
            found = [item for item in found if item.tenant_id == tenant_id.lower()]
        return sorted(found, key=lambda item: item.name.casefold())

    # Resource Graph ---------------------------------------------------------------

    def resource_graph(
        self, query: str, *, subscriptions: Iterable[str] = (), limit: int = 1000
    ) -> QueryResult:
        """Run an Azure Resource Graph (KQL) query, following ``$skipToken`` up to ``limit``.

        Without ``subscriptions`` the query covers every subscription the credential can
        read in the tenant.
        """
        if not query.strip():
            raise LdoError("the Resource Graph query is empty")
        scope = [_subscription_id(item) for item in subscriptions]
        rows: list[dict[str, Any]] = []
        skip_token: str | None = None
        truncated = False
        while True:
            options: dict[str, Any] = {
                "resultFormat": "objectArray",
                "$top": min(_GRAPH_PAGE, limit - len(rows)),
            }
            if skip_token:
                options["$skipToken"] = skip_token
            body: dict[str, Any] = {"query": query, "options": options}
            if scope:
                body["subscriptions"] = scope
            page = self.api.post(
                "/providers/Microsoft.ResourceGraph/resources",
                body,
                params={"api-version": RESOURCE_GRAPH_API},
            )
            data = page.get("data")
            if isinstance(data, list):
                rows.extend(row for row in data if isinstance(row, dict))
            token = page.get("$skipToken")
            skip_token = token if isinstance(token, str) and token else None
            if skip_token is None:
                break
            if len(rows) >= limit:
                truncated = True
                break
        return QueryResult.from_records(rows, truncated=truncated)

    # RBAC -------------------------------------------------------------------------

    def role_assignments(
        self, principal_id: str, subscription_ids: Iterable[str]
    ) -> list[AzureRoleAssignment]:
        """Every role assignment that applies to ``principal_id`` in the subscriptions.

        ``assignedTo()`` includes assignments made to groups the principal belongs to,
        and those inherited from management groups above each subscription.
        """
        principal_id = _guid(principal_id, "principal id")
        seen: dict[str, AzureRoleAssignment] = {}
        for subscription_id in subscription_ids:
            items = self.api.get_all(
                f"/subscriptions/{_subscription_id(subscription_id)}"
                "/providers/Microsoft.Authorization/roleAssignments",
                params={
                    "api-version": AUTHORIZATION_API,
                    "$filter": f"assignedTo('{principal_id}')",
                },
                next_link="nextLink",
            )
            for item in items:
                assignment_id = str(item.get("id") or "")
                if assignment_id and assignment_id not in seen:
                    properties = item.get("properties")
                    definition = (
                        str(properties.get("roleDefinitionId") or "")
                        if isinstance(properties, dict)
                        else ""
                    )
                    seen[assignment_id] = AzureRoleAssignment.from_json(
                        item, self._role_name(definition)
                    )
        return sorted(seen.values(), key=lambda item: (item.scope.casefold(), item.role_name))

    def _role_name(self, definition_id: str) -> str:
        if not definition_id:
            return ""
        if definition_id not in self._role_names:
            try:
                data = self.api.get(definition_id, params={"api-version": AUTHORIZATION_API})
                properties = data.get("properties")
                name = str(properties.get("roleName") or "") if isinstance(properties, dict) else ""
            except ApiError:
                # The assignment is still worth showing without a friendly name.
                name = ""
            self._role_names[definition_id] = name or definition_id.rsplit("/", 1)[-1]
        return self._role_names[definition_id]

    # Defender for Cloud -----------------------------------------------------------

    def secure_score(self, subscription_id: str) -> SecureScore | None:
        """The subscription's secure score, or None where Defender for Cloud has none."""
        subscription_id = _subscription_id(subscription_id)
        try:
            data = self.api.get(
                f"/subscriptions/{subscription_id}/providers/Microsoft.Security/secureScores/ascScore",
                params={"api-version": SECURE_SCORE_API},
            )
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise
        return SecureScore.from_json(subscription_id, data)

    def secure_score_controls(self, subscription_id: str) -> list[SecureScoreControl]:
        """Security controls, the ones costing the most points first."""
        items = self.api.get_all(
            f"/subscriptions/{_subscription_id(subscription_id)}"
            "/providers/Microsoft.Security/secureScoreControls",
            params={"api-version": SECURE_SCORE_API, "$expand": "definition"},
            next_link="nextLink",
        )
        controls = [SecureScoreControl.from_json(item) for item in items]
        return sorted(controls, key=lambda control: control.points_lost, reverse=True)

    def assessments(self, subscription_id: str, *, unhealthy_only: bool = True) -> list[Assessment]:
        """Defender for Cloud recommendation results, most severe first."""
        items = self.api.get_all(
            f"/subscriptions/{_subscription_id(subscription_id)}"
            "/providers/Microsoft.Security/assessments",
            params={"api-version": ASSESSMENTS_API, "$expand": "metadata"},
            next_link="nextLink",
        )
        found = [Assessment.from_json(item) for item in items]
        if unhealthy_only:
            found = [item for item in found if item.unhealthy]
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(found, key=lambda item: (order.get(item.severity.casefold(), 3), item.name))

    def defender_plans(self, subscription_id: str) -> list[DefenderPlan]:
        """Every Defender for Cloud plan on the subscription and its tier."""
        data = self.api.get(
            f"/subscriptions/{_subscription_id(subscription_id)}/providers/Microsoft.Security/pricings",
            params={"api-version": PRICINGS_API},
        )
        items = data.get("value")
        plans = [
            DefenderPlan.from_json(item)
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        ]
        return sorted(plans, key=lambda plan: plan.name.casefold())


def _guid(value: str, what: str) -> str:
    if not is_guid(value):
        raise LdoError(f"not a {what}: {value!r}")
    return value.strip().lower()


def _subscription_id(value: str) -> str:
    return _guid(value, "subscription id")
