"""Azure Resource Manager records, trimmed to the fields used here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields


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
        """A subscription as ARM lists it."""
        return cls(
            id=fields.text(data, "subscriptionId").lower(),
            name=fields.text(data, "displayName"),
            state=fields.text(data, "state"),
            tenant_id=fields.text(data, "tenantId").lower(),
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
        """A role assignment as ARM returns it, with its role's name looked up separately."""
        properties = fields.mapping(data.get("properties"))
        return cls(
            id=fields.text(data, "id"),
            scope=fields.text(properties, "scope"),
            role_name=role_name,
            role_definition_id=fields.text(properties, "roleDefinitionId"),
            principal_id=fields.text(properties, "principalId"),
            principal_type=fields.text(properties, "principalType"),
            condition=fields.text(properties, "condition"),
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
        """``subscription_id``'s secure score as Defender for Cloud returns it."""
        score = fields.mapping(fields.mapping(data.get("properties")).get("score"))
        return cls(
            subscription_id=subscription_id,
            current=fields.number(score.get("current")),
            max=fields.number(score.get("max")),
            percentage=fields.number(score.get("percentage")),
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
        """The points this control could still earn."""
        return (self.max or 0.0) - (self.current or 0.0)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SecureScoreControl:
        """One secure score control, with how many resources pass and fail it."""
        properties = fields.mapping(data.get("properties"))
        score = fields.mapping(properties.get("score"))

        def count(key: str) -> int:
            value = properties.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else 0

        return cls(
            name=fields.text(properties, "displayName") or fields.text(data, "name"),
            current=fields.number(score.get("current")),
            max=fields.number(score.get("max")),
            percentage=fields.number(score.get("percentage")),
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
        """Whether the resource fails the assessment."""
        return self.status.casefold() == "unhealthy"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Assessment:
        """One assessment of one resource, whose id is the assessment's without its last part."""
        properties = fields.mapping(data.get("properties"))
        status = fields.mapping(properties.get("status"))
        metadata = fields.mapping(properties.get("metadata"))
        assessment_id = fields.text(data, "id")
        # The assessment id is the resource id with the assessment appended.
        resource_id = assessment_id.split("/providers/Microsoft.Security/assessments/", 1)[0]
        return cls(
            id=assessment_id,
            name=fields.text(properties, "displayName") or fields.text(data, "name"),
            status=fields.text(status, "code"),
            severity=fields.text(metadata, "severity"),
            resource_id=resource_id,
            cause=fields.text(status, "cause") or fields.text(status, "description"),
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
        """Whether the plan is on (the Standard tier; Free is off)."""
        return self.pricing_tier.casefold() == "standard"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DefenderPlan:
        """One Defender for Cloud plan as ARM returns it."""
        properties = fields.mapping(data.get("properties"))
        return cls(
            name=fields.text(data, "name"),
            pricing_tier=fields.text(properties, "pricingTier"),
            sub_plan=fields.text(properties, "subPlan"),
            trial_remaining=fields.text(properties, "freeTrialRemainingTime"),
            enabled_since=fields.when(properties, "enablementTime"),
            deprecated=properties.get("deprecated") is True,
            raw=dict(data),
        )
