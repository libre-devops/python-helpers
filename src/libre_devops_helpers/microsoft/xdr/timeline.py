"""A device's timeline, from Advanced Hunting: the events the Defender portal's timeline shows.

Defender has no API for the device timeline. The portal's timeline page reads an internal
service of its own, which Microsoft neither documents nor supports, and which accepts no
token an app registration or the Azure CLI can get. The events behind that page are in
Advanced Hunting's device tables, though, and those the supported hunting APIs can query:
Graph's ``runHuntingQuery`` (ThreatHunting.Read.All) or Defender for Endpoint's
``advancedqueries/run`` (AdvancedQuery.Read). So a timeline here is one query over those
tables, for one device and one window of time, newest first.

Compared with the portal's own timeline:

- Advanced Hunting keeps 30 days of device events (``RETENTION``); the portal's timeline
  reaches further back.
- A query returns at most 100,000 rows, and every query counts against the tenant's
  hunting quota. So only the newest ``limit`` events are asked for: a busy server writes
  thousands an hour, and narrowing the window or the kinds of event is kinder than a
  higher limit.
- What the portal adds on top of the events (flags set on the timeline, its grouping of
  related events, techniques shown inline) is not in the tables.
- The tables keep UTC.

The query is fixed text around values checked first: the device name
(``core.util.require_host``), the kinds of event (from ``KINDS``), the window (datetimes,
written here) and the limit (a whole number in range). Nothing else a person types reaches
it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.timewindow import Window
from libre_devops_helpers.core.util import require_host, short_name, split_names

# How far back Advanced Hunting keeps device events.
RETENTION = timedelta(days=30)
# The most rows one hunting query returns, and the events asked for by default.
MAX_EVENTS = 100_000
DEFAULT_LIMIT = 1000


@dataclass(frozen=True)
class _Kind:
    """One kind of event: the table that holds it, and KQL for its detail and account."""

    table: str
    detail: str
    account: str


# Each kind's table, and what it shows: the detail a person reads first (a command line, a
# connection, a path), and the account behind it. coalesce() takes the first that is not
# empty. The alert kind is built apart, from AlertEvidence and AlertInfo.
KINDS: dict[str, _Kind | None] = {
    "process": _Kind(
        "DeviceProcessEvents",
        "coalesce(ProcessCommandLine, FolderPath, FileName)",
        "coalesce(AccountName, InitiatingProcessAccountName)",
    ),
    "network": _Kind(
        "DeviceNetworkEvents",
        'iff(isempty(RemoteIP), strcat("listening on ", LocalIP, ":", LocalPort), '
        'strcat(RemoteIP, ":", RemotePort, iff(isempty(RemoteUrl), "", strcat(" ", RemoteUrl))))',
        "InitiatingProcessAccountName",
    ),
    "file": _Kind(
        "DeviceFileEvents",
        "coalesce(FolderPath, FileName)",
        "coalesce(RequestAccountName, InitiatingProcessAccountName)",
    ),
    "registry": _Kind(
        "DeviceRegistryEvents",
        'strcat(RegistryKey, iff(isempty(RegistryValueName), "", '
        'strcat(" ", RegistryValueName, " = ", RegistryValueData)))',
        "InitiatingProcessAccountName",
    ),
    "logon": _Kind(
        "DeviceLogonEvents",
        'strcat(LogonType, iff(isempty(RemoteIP), "", strcat(" from ", RemoteIP)))',
        "AccountName",
    ),
    "image-load": _Kind(
        "DeviceImageLoadEvents",
        "coalesce(FolderPath, FileName)",
        "InitiatingProcessAccountName",
    ),
    "other": _Kind(
        "DeviceEvents",
        "coalesce(ProcessCommandLine, FolderPath, FileName, RemoteUrl, RemoteIP)",
        "coalesce(AccountName, InitiatingProcessAccountName)",
    ),
    "alert": None,
}


@dataclass(frozen=True)
class TimelineEvent:
    """One event on a device's timeline. ``kind`` is one of ``KINDS``; ``action`` is its
    ActionType (for an alert, its severity); ``id`` the event's ReportId, or the AlertId."""

    time: datetime | None
    kind: str
    action: str
    detail: str
    account: str
    process: str
    device_name: str
    device_id: str
    id: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> TimelineEvent:
        """An event from one row of ``timeline_query``'s result."""
        return cls(
            time=fields.when(row, "Timestamp"),
            kind=fields.text(row, "Type"),
            action=fields.text(row, "ActionType"),
            detail=fields.text(row, "Detail"),
            account=fields.text(row, "Account"),
            process=fields.text(row, "Process"),
            device_name=fields.text(row, "DeviceName"),
            device_id=fields.text(row, "DeviceId"),
            id=fields.text(row, "Id"),
            raw=dict(row),
        )


@dataclass(frozen=True)
class Timeline:
    """A device's events, newest first, as one query found them."""

    device: str
    events: tuple[TimelineEvent, ...]
    limit: int

    @property
    def truncated(self) -> bool:
        """Whether the query stopped at ``limit``, so older events in the window are left out."""
        return len(self.events) >= self.limit

    @property
    def devices(self) -> tuple[str, ...]:
        """Each device the events came from, by name and id: more than one when devices
        share the name (a rebuilt server keeps its name and gets a new id)."""
        return tuple(
            dict.fromkeys(f"{event.device_name} ({event.device_id})" for event in self.events)
        )


def parse_kinds(values: Iterable[str]) -> tuple[str, ...]:
    """The kinds of event named, in ``KINDS`` order ("process,network", or repeated); all
    of them when none are named."""
    named = {value.casefold() for value in split_names(values)}
    unknown = sorted(named - set(KINDS))
    if unknown:
        raise InputError(
            f"unknown kind of event: {', '.join(unknown)}", hint=f"use {', '.join(KINDS)}"
        )
    return tuple(kind for kind in KINDS if not named or kind in named)


def timeline_query(
    device: str, window: Window, kinds: Iterable[str] = (), limit: int = DEFAULT_LIMIT
) -> str:
    """The KQL for ``device``'s events in ``window``: the newest ``limit`` of the ``kinds``
    asked for (every kind when none are), each shaped to the same columns."""
    if not 1 <= limit <= MAX_EVENTS:
        raise InputError(f"the limit must be from 1 to {MAX_EVENTS:,}, not {limit}")
    chosen = parse_kinds(kinds)
    lines = [f"let device = dynamic({json.dumps(_names(device))});"]
    lines += [f"let {_let_name(kind)} = {_part(kind, window, device)};" for kind in chosen]
    lines.append(f"union {', '.join(_let_name(kind) for kind in chosen)}")
    lines.append(f"| top {limit} by Timestamp desc")
    return "\n".join(lines)


def read_timeline(device: str, result: QueryResult, limit: int = DEFAULT_LIMIT) -> Timeline:
    """``result`` (of ``timeline_query``) as a Timeline, newest first."""
    events = [TimelineEvent.from_row(row) for row in result.rows]
    events.sort(key=lambda event: event.time or datetime.min.replace(tzinfo=UTC), reverse=True)
    return Timeline(device, tuple(events), limit)


def outside_retention(window: Window, now: datetime) -> bool:
    """Whether ``window`` reaches back past what Advanced Hunting keeps (or has no start)."""
    return window.start is None or window.start < now - RETENTION


def _names(device: str) -> list[str]:
    """The names to match, lower case: an FQDN and its host name, or a host name alone."""
    name = require_host(device).lower()
    return list(dict.fromkeys([name, short_name(name)]))


def _device_filter(device: str) -> str:
    """Rows from ``device``, by the names the query's ``device`` list holds. A host name on
    its own also finds the device by its first label (``web01`` finds
    ``web01.corp.example``), never a longer name (``web010``)."""
    name = require_host(device).lower()
    if "." in name:
        return "DeviceName in~ (device)"
    return f"DeviceName in~ (device) or DeviceName startswith {json.dumps(name + '.')}"


def _time_filter(window: Window) -> str:
    bounds = []
    if window.start is not None:
        bounds.append(f"Timestamp >= {_kql_time(window.start)}")
    if window.end is not None:
        bounds.append(f"Timestamp < {_kql_time(window.end)}")
    return " and ".join(bounds) or "true"


def _part(kind: str, window: Window, device: str) -> str:
    """One kind's rows, filtered to the window and the device, in the shared columns."""
    where = f"| where {_time_filter(window)}\n    | where {_device_filter(device)}"
    shape = KINDS[kind]
    if shape is None:
        # An alert's evidence is a row per entity: the first one on this device dates it.
        return (
            f"AlertEvidence\n    {where}\n"
            "    | summarize Timestamp = min(Timestamp) by AlertId, DeviceName, DeviceId\n"
            "    | join kind=leftouter (AlertInfo | summarize arg_max(Timestamp, Title, Severity)"
            " by AlertId) on AlertId\n"
            '    | project Timestamp, Type = "alert", ActionType = Severity, Detail = Title,'
            ' Account = "", Process = "", DeviceName, DeviceId, Id = AlertId'
        )
    return (
        f"{shape.table}\n    {where}\n"
        f'    | project Timestamp, Type = "{kind}", ActionType, Detail = {shape.detail},\n'
        f"        Account = {shape.account}, Process = InitiatingProcessFileName,\n"
        "        DeviceName, DeviceId, Id = tostring(ReportId)"
    )


def _let_name(kind: str) -> str:
    return kind.replace("-", "_") + "_events"


def _kql_time(moment: datetime) -> str:
    return f"datetime({moment.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ})"
