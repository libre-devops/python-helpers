"""Defender XDR incidents and their alerts, as the Graph security API returns them.

In the unified security operations platform, one incident queue holds Defender's own
incidents and those from Microsoft Sentinel. Each alert names the service that raised
it (``serviceSource``), which is how an incident is known to come from Sentinel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields

# Graph's serviceSource values, and a short name for each.
SOURCES = {
    "microsoftDefenderForEndpoint": "Endpoint",
    "microsoftDefenderForIdentity": "Identity",
    "microsoftDefenderForCloudApps": "Cloud Apps",
    "microsoftDefenderForOffice365": "Office 365",
    "microsoft365Defender": "XDR",
    "azureAdIdentityProtection": "Entra ID Protection",
    "microsoftAppGovernance": "App Governance",
    "dataLossPrevention": "DLP",
    "microsoftDefenderForCloud": "Defender for Cloud",
    "microsoftSentinel": "Sentinel",
    "microsoftInsiderRiskManagement": "Insider Risk",
}
# Most severe first; unknown values rank below informational.
SEVERITY_ORDER = ("high", "medium", "low", "informational")
# Graph's status values; "open" means any of the first three.
OPEN_STATUSES = ("active", "inProgress", "awaitingAction")
STATUSES = (*OPEN_STATUSES, "resolved", "redirected")


def severity_rank(severity: str) -> int:
    """0 for high, up to 4 for unknown: sort ascending for most severe first."""
    try:
        return SEVERITY_ORDER.index(severity.lower())
    except ValueError:
        return len(SEVERITY_ORDER)


@dataclass(frozen=True)
class IncidentAlert:
    """One alert in an incident."""

    id: str
    title: str
    severity: str
    status: str
    source: str  # Graph's serviceSource
    detection_source: str
    created: datetime | None
    devices: tuple[str, ...] = ()
    users: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def source_name(self) -> str:
        """The product that raised the alert, by the name the portal gives it."""
        return SOURCES.get(self.source, self.source or "unknown")

    @classmethod
    def from_graph(cls, record: Mapping[str, Any]) -> IncidentAlert:
        """An alert as Graph returns it, with the devices and users named in its evidence."""
        devices: list[str] = []
        users: list[str] = []
        for evidence in record.get("evidence") or ():
            if not isinstance(evidence, Mapping):
                continue
            kind = fields.text(evidence, "@odata.type")
            if kind.endswith("deviceEvidence"):
                name = evidence.get("deviceDnsName") or evidence.get("hostName")
                if name:
                    devices.append(str(name))
            elif kind.endswith("userEvidence"):
                account = evidence.get("userAccount") or {}
                name = account.get("userPrincipalName") or account.get("accountName")
                if name:
                    users.append(str(name))
        return cls(
            id=fields.text(record, "id"),
            title=fields.text(record, "title"),
            severity=fields.text(record, "severity"),
            status=fields.text(record, "status"),
            source=fields.text(record, "serviceSource"),
            detection_source=fields.text(record, "detectionSource"),
            created=fields.when(record, "createdDateTime"),
            devices=tuple(dict.fromkeys(devices)),
            users=tuple(dict.fromkeys(users)),
            raw=dict(record),
        )


@dataclass(frozen=True)
class Incident:
    """One incident, with its alerts."""

    id: str
    title: str
    severity: str
    status: str
    created: datetime | None
    updated: datetime | None
    assigned_to: str
    classification: str
    determination: str
    web_url: str
    tags: tuple[str, ...]
    alerts: tuple[IncidentAlert, ...]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def open(self) -> bool:
        """Whether the incident is still open (active, in progress, or awaiting action)."""
        return self.status in OPEN_STATUSES

    @property
    def sources(self) -> tuple[str, ...]:
        """The services that raised its alerts (Graph values), in first-seen order."""
        return tuple(dict.fromkeys(alert.source for alert in self.alerts if alert.source))

    @property
    def source_names(self) -> tuple[str, ...]:
        """The products that raised the incident's alerts, by their portal names."""
        return tuple(SOURCES.get(source, source) for source in self.sources)

    @property
    def devices(self) -> tuple[str, ...]:
        """Every device the alerts name, once each, in order."""
        return tuple(dict.fromkeys(name for alert in self.alerts for name in alert.devices))

    @property
    def users(self) -> tuple[str, ...]:
        """Every user the alerts name, once each, in order."""
        return tuple(dict.fromkeys(name for alert in self.alerts for name in alert.users))

    @classmethod
    def from_graph(cls, record: Mapping[str, Any]) -> Incident:
        """An incident as Graph returns it, with its alerts when they were expanded."""
        tags = [*(record.get("customTags") or ()), *(record.get("systemTags") or ())]
        return cls(
            id=fields.text(record, "id"),
            title=fields.text(record, "displayName"),
            severity=fields.text(record, "severity"),
            status=fields.text(record, "status"),
            created=fields.when(record, "createdDateTime"),
            updated=fields.when(record, "lastUpdateDateTime"),
            assigned_to=fields.text(record, "assignedTo"),
            classification=fields.text(record, "classification"),
            determination=fields.text(record, "determination"),
            web_url=fields.text(record, "incidentWebUrl"),
            tags=tuple(str(tag) for tag in tags),
            alerts=tuple(
                IncidentAlert.from_graph(alert)
                for alert in record.get("alerts") or ()
                if isinstance(alert, Mapping)
            ),
            raw=dict(record),
        )
