"""Defender for Endpoint records (machines, alerts, vulnerabilities, indicators), trimmed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core.util import parse_datetime


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
        tags = data.get("machineTags")
        return cls(
            id=str(data.get("id", "")),
            computer_dns_name=str(data.get("computerDnsName") or ""),
            onboarding_status=str(data.get("onboardingStatus") or ""),
            health_status=str(data.get("healthStatus") or ""),
            last_seen=parse_datetime(data.get("lastSeen")),
            first_seen=parse_datetime(data.get("firstSeen")),
            os_platform=str(data.get("osPlatform") or ""),
            os_version=str(data.get("osVersion") or ""),
            agent_version=str(data.get("version") or ""),
            machine_tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
            risk_score=str(data.get("riskScore") or ""),
            exposure_level=str(data.get("exposureLevel") or ""),
            last_ip_address=str(data.get("lastIpAddress") or ""),
            aad_device_id=str(data.get("aadDeviceId") or ""),
            device_group=str(data.get("rbacGroupName") or ""),
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
        return bool(self.records)

    @property
    def machine(self) -> Machine | None:
        """The newest record, which is the one to trust."""
        return self.records[0] if self.records else None


def _text(data: Mapping[str, Any], key: str) -> str:
    return str(data.get(key) or "")


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
        return self.status.casefold() == "resolved"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Alert:
        return cls(
            id=_text(data, "id"),
            title=_text(data, "title"),
            severity=_text(data, "severity"),
            status=_text(data, "status"),
            category=_text(data, "category"),
            detection_source=_text(data, "detectionSource"),
            machine_id=_text(data, "machineId"),
            computer_dns_name=_text(data, "computerDnsName"),
            incident_id=_text(data, "incidentId"),
            created=parse_datetime(data.get("alertCreationTime")),
            last_activity=parse_datetime(data.get("lastEventTime") or data.get("lastUpdateTime")),
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
        cvss = data.get("cvssV3")
        return cls(
            id=_text(data, "id"),
            name=_text(data, "name"),
            severity=_text(data, "severity"),
            cvss=float(cvss)
            if isinstance(cvss, int | float) and not isinstance(cvss, bool)
            else None,
            exploit_verified=data.get("exploitVerified") is True,
            public_exploit=data.get("publicExploit") is True,
            published=parse_datetime(data.get("publishedOn")),
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
        return cls(
            id=_text(data, "id"),
            value=_text(data, "indicatorValue"),
            indicator_type=_text(data, "indicatorType"),
            action=_text(data, "action"),
            title=_text(data, "title"),
            severity=_text(data, "severity"),
            expires=parse_datetime(data.get("expirationTime")),
            created_by=_text(data, "createdBy"),
            raw=dict(data),
        )
