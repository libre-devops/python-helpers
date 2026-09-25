"""Defender XDR custom detection rules, as Graph's ``security/rules/detectionRules`` returns them.

Custom detection rules are Defender XDR's own analytics rules: an Advanced Hunting query on
a schedule, and the alert (and any automated response) it raises. With Sentinel run from
the Defender portal they are where detections now live.

This reads the current shape of the API: ``status``, ``schedule``, ``queryCondition`` and
``detectionAction``. Microsoft removes the legacy properties (``isEnabled``, ``detectorId``,
``lastRunDetails`` and others) on 2026-10-01, so nothing here depends on them; until then a
rule written the old way may carry only ``isEnabled`` or a schedule ``period``, which are
read as a fallback. With ``lastRunDetails`` gone, the API no longer says how a rule's last
run went: a ``status`` of ``autoDisabled``, Defender turning the rule off itself (usually
after its query failed again and again), is the signal that is left.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields

# The statuses a rule can have, and what each means to a person.
STATUSES = {
    "enabled": "enabled",
    "disabled": "disabled",
    "autodisabled": "turned off by Defender",
}
# How often a rule runs (``schedule.frequency``), as a person says it. PT0S is continuous:
# the rule runs on events as they arrive (near real time).
FREQUENCIES = {
    "PT0S": "continuous",
    "PT1H": "every 1h",
    "PT3H": "every 3h",
    "PT12H": "every 12h",
    "PT24H": "every 24h",
    "P1D": "every 24h",
}
# The legacy ``schedule.period`` (removed on 2026-10-01), as the frequency it stood for.
LEGACY_PERIODS = {"0": "PT0S", "1H": "PT1H", "3H": "PT3H", "12H": "PT12H", "24H": "PT24H"}


@dataclass(frozen=True)
class DetectionRule:
    """One custom detection rule. ``tactics`` are its ATT&CK tactics in the order the rule
    lists them, and ``techniques`` its techniques and sub-techniques, together."""

    id: str
    display_name: str
    description: str
    status: str
    frequency: str
    next_run: datetime | None
    title: str
    severity: str
    tactics: tuple[str, ...]
    techniques: tuple[str, ...]
    query: str
    created_by: str
    created: datetime | None
    modified_by: str
    modified: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def auto_disabled(self) -> bool:
        """Whether Defender turned the rule off itself, usually after its query kept failing."""
        return self.status.casefold() == "autodisabled"

    @property
    def schedule(self) -> str:
        """How often it runs, as a person says it: ``continuous``, ``every 3h``."""
        return FREQUENCIES.get(self.frequency, self.frequency or "-")

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DetectionRule:
        """A rule as Graph returns it, in the current shape or the legacy one."""
        schedule = fields.mapping(data.get("schedule"))
        template = alert_template(data)
        tactics, techniques = _mitre(template)
        return cls(
            id=fields.text(data, "id"),
            display_name=fields.text(data, "displayName"),
            description=fields.text(data, "description"),
            status=rule_status(data),
            frequency=rule_frequency(data),
            next_run=fields.when(schedule, "nextRunDateTime"),
            title=fields.text(template, "title"),
            severity=fields.text(template, "severity"),
            tactics=tactics,
            techniques=techniques,
            query=fields.text(fields.mapping(data.get("queryCondition")), "queryText"),
            created_by=fields.text(data, "createdBy"),
            created=fields.when(data, "createdDateTime"),
            modified_by=fields.text(data, "lastModifiedBy"),
            modified=fields.when(data, "lastModifiedDateTime"),
            raw=dict(data),
        )


def alert_template(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """The alert a rule raises: ``detectionAction.alertTemplate``."""
    return fields.mapping(fields.mapping(data.get("detectionAction")).get("alertTemplate"))


def rule_status(data: Mapping[str, Any]) -> str:
    """``status``, else what the legacy ``isEnabled`` said, else empty."""
    status = fields.text(data, "status")
    if status:
        return status
    enabled = fields.flag(data.get("isEnabled"))
    return "" if enabled is None else "enabled" if enabled else "disabled"


def rule_frequency(data: Mapping[str, Any]) -> str:
    """``schedule.frequency`` (ISO 8601), else the legacy ``period`` as one, else empty."""
    schedule = fields.mapping(data.get("schedule"))
    return fields.text(schedule, "frequency") or LEGACY_PERIODS.get(
        fields.text(schedule, "period"), ""
    )


def _mitre(template: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The tactics, and every technique and sub-technique under them; the legacy
    ``category`` and ``mitreTechniques`` when a rule has no ``tactics``."""
    tactics: list[str] = []
    techniques: list[str] = []
    for entry in fields.items(template.get("tactics")):
        tactic = fields.mapping(entry)
        tactics.append(fields.text(tactic, "tactic"))
        for technique in fields.items(tactic.get("techniques")):
            found = fields.mapping(technique)
            techniques.append(fields.text(found, "technique"))
            techniques.extend(str(sub) for sub in fields.items(found.get("subTechniques")))
    if not tactics and fields.text(template, "category"):
        tactics.append(fields.text(template, "category"))
        techniques.extend(str(item) for item in fields.items(template.get("mitreTechniques")))
    return tuple(item for item in tactics if item), tuple(item for item in techniques if item)
