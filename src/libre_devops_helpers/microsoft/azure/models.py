"""Azure Resource Manager records, trimmed to the fields used here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core.util import parse_datetime


def _map(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(data: Mapping[str, Any], key: str) -> str:
    return str(data.get(key) or "")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


@dataclass(frozen=True)
class Subscription:
    """An Azure subscription the credential can see."""

    id: str
    name: str
    state: str
    tenant_id: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Subscription:
        return cls(
            id=_text(data, "subscriptionId").lower(),
            name=_text(data, "displayName"),
            state=_text(data, "state"),
            tenant_id=_text(data, "tenantId").lower(),
            raw=dict(data),
        )


@dataclass(frozen=True)
class AzureRoleAssignment:
    """An Azure RBAC role assignment. ``role_name`` is resolved from the definition."""

    id: str
    scope: str
    role_name: str
    role_definition_id: str
    principal_id: str
    principal_type: str
    condition: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], role_name: str) -> AzureRoleAssignment:
        properties = _map(data.get("properties"))
        return cls(
            id=_text(data, "id"),
            scope=_text(properties, "scope"),
            role_name=role_name,
            role_definition_id=_text(properties, "roleDefinitionId"),
            principal_id=_text(properties, "principalId"),
            principal_type=_text(properties, "principalType"),
            condition=_text(properties, "condition"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class SecureScore:
    """A subscription's Defender for Cloud secure score."""

    subscription_id: str
    current: float | None
    max: float | None
    percentage: float | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, subscription_id: str, data: Mapping[str, Any]) -> SecureScore:
        score = _map(_map(data.get("properties")).get("score"))
        return cls(
            subscription_id=subscription_id,
            current=_number(score.get("current")),
            max=_number(score.get("max")),
            percentage=_number(score.get("percentage")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class SecureScoreControl:
    """One security control and how much of the secure score it is costing."""

    name: str
    current: float | None
    max: float | None
    percentage: float | None
    healthy: int
    unhealthy: int
    not_applicable: int
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def points_lost(self) -> float:
        return (self.max or 0.0) - (self.current or 0.0)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SecureScoreControl:
        properties = _map(data.get("properties"))
        score = _map(properties.get("score"))

        def count(key: str) -> int:
            value = properties.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else 0

        return cls(
            name=_text(properties, "displayName") or _text(data, "name"),
            current=_number(score.get("current")),
            max=_number(score.get("max")),
            percentage=_number(score.get("percentage")),
            healthy=count("healthyResourceCount"),
            unhealthy=count("unhealthyResourceCount"),
            not_applicable=count("notApplicableResourceCount"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Assessment:
    """A Defender for Cloud recommendation's result for one resource."""

    id: str
    name: str
    status: str
    severity: str
    resource_id: str
    cause: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def unhealthy(self) -> bool:
        return self.status.casefold() == "unhealthy"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Assessment:
        properties = _map(data.get("properties"))
        status = _map(properties.get("status"))
        metadata = _map(properties.get("metadata"))
        assessment_id = _text(data, "id")
        # The assessment id is the resource id with the assessment appended.
        resource_id = assessment_id.split("/providers/Microsoft.Security/assessments/", 1)[0]
        return cls(
            id=assessment_id,
            name=_text(properties, "displayName") or _text(data, "name"),
            status=_text(status, "code"),
            severity=_text(metadata, "severity"),
            resource_id=resource_id,
            cause=_text(status, "cause") or _text(status, "description"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class DefenderPlan:
    """A Defender for Cloud plan and whether it is on (Standard) or off (Free)."""

    name: str
    pricing_tier: str
    sub_plan: str
    trial_remaining: str
    enabled_since: datetime | None
    deprecated: bool
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def enabled(self) -> bool:
        return self.pricing_tier.casefold() == "standard"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DefenderPlan:
        properties = _map(data.get("properties"))
        return cls(
            name=_text(data, "name"),
            pricing_tier=_text(properties, "pricingTier"),
            sub_plan=_text(properties, "subPlan"),
            trial_remaining=_text(properties, "freeTrialRemainingTime"),
            enabled_since=parse_datetime(properties.get("enablementTime")),
            deprecated=properties.get("deprecated") is True,
            raw=dict(data),
        )
