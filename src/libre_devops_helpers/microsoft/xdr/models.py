"""Defender for Endpoint records (machines, alerts, vulnerabilities, indicators), trimmed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields


@dataclass(frozen=True)
class Machine:
    """One MDE machine record. ``raw`` keeps the full API record for JSON output."""

    id: str
    computer_dns_name: str
    onboarding_status: str
    health_status: str
    last_seen: datetime | None
    first_seen: datetime | None
    os_platform: str
    os_version: str
    agent_version: str
    machine_tags: tuple[str, ...]
    risk_score: str
    exposure_level: str
    last_ip_address: str
    aad_device_id: str
    # The Defender device group (set up under Settings > Endpoints > Device groups) the
    # machine falls in; "UnassignedGroup" when it matches none.
    device_group: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Machine:
        """A machine as Defender for Endpoint returns it."""
        tags = data.get("machineTags")
        return cls(
            id=fields.text(data, "id"),
            computer_dns_name=fields.text(data, "computerDnsName"),
            onboarding_status=fields.text(data, "onboardingStatus"),
            health_status=fields.text(data, "healthStatus"),
            last_seen=fields.when(data, "lastSeen"),
            first_seen=fields.when(data, "firstSeen"),
            os_platform=fields.text(data, "osPlatform"),
            os_version=fields.text(data, "osVersion"),
            agent_version=fields.text(data, "version"),
            machine_tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
            risk_score=fields.text(data, "riskScore"),
            exposure_level=fields.text(data, "exposureLevel"),
            last_ip_address=fields.text(data, "lastIpAddress"),
            aad_device_id=fields.text(data, "aadDeviceId"),
            device_group=fields.text(data, "rbacGroupName"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class MachineLookup:
    """The result of looking one device up by name.

    ``matched_name`` is the name that found records (the FQDN, or the short
    hostname fallback), or None. ``records`` is newest ``lastSeen`` first;
    more than one means MDE holds duplicate records for the device.
    """

    query: str
    matched_name: str | None
    records: tuple[Machine, ...] = ()

    @property
    def found(self) -> bool:
        """Whether Defender has any record with the name."""
        return bool(self.records)

    @property
    def machine(self) -> Machine | None:
        """The newest record, which is the one to trust."""
        return self.records[0] if self.records else None


@dataclass(frozen=True)
class Alert:
    """A Defender for Endpoint alert."""

    id: str
    title: str
    severity: str
    status: str
    category: str
    detection_source: str
    machine_id: str
    computer_dns_name: str
    incident_id: str
    created: datetime | None
    last_activity: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def resolved(self) -> bool:
        """Whether the alert is resolved."""
        return self.status.casefold() == "resolved"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Alert:
        """An alert as Defender for Endpoint returns it."""
        return cls(
            id=fields.text(data, "id"),
            title=fields.text(data, "title"),
            severity=fields.text(data, "severity"),
            status=fields.text(data, "status"),
            category=fields.text(data, "category"),
            detection_source=fields.text(data, "detectionSource"),
            machine_id=fields.text(data, "machineId"),
            computer_dns_name=fields.text(data, "computerDnsName"),
            incident_id=fields.text(data, "incidentId"),
            created=fields.when(data, "alertCreationTime"),
            last_activity=(
                fields.when(data, "lastEventTime") or fields.when(data, "lastUpdateTime")
            ),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Vulnerability:
    """A vulnerability (CVE) Defender reports on a machine."""

    id: str
    name: str
    severity: str
    cvss: float | None
    exploit_verified: bool
    public_exploit: bool
    published: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Vulnerability:
        """A vulnerability as Defender for Endpoint returns it; ``cvss`` is its CVSS v3 score, when
        it has one."""
        cvss = data.get("cvssV3")
        return cls(
            id=fields.text(data, "id"),
            name=fields.text(data, "name"),
            severity=fields.text(data, "severity"),
            cvss=float(cvss)
            if isinstance(cvss, int | float) and not isinstance(cvss, bool)
            else None,
            exploit_verified=data.get("exploitVerified") is True,
            public_exploit=data.get("publicExploit") is True,
            published=fields.when(data, "publishedOn"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Indicator:
    """A custom indicator of compromise (file hash, IP, URL, domain or certificate)."""

    id: str
    value: str
    indicator_type: str
    action: str
    title: str
    severity: str
    expires: datetime | None
    created_by: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Indicator:
        """A custom indicator as Defender for Endpoint returns it."""
        return cls(
            id=fields.text(data, "id"),
            value=fields.text(data, "indicatorValue"),
            indicator_type=fields.text(data, "indicatorType"),
            action=fields.text(data, "action"),
            title=fields.text(data, "title"),
            severity=fields.text(data, "severity"),
            expires=fields.when(data, "expirationTime"),
            created_by=fields.text(data, "createdBy"),
            raw=dict(data),
        )
