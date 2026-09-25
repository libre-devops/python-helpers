"""Defender Antivirus versions on devices: the signature, engine and platform, by KQL.

The versions come from Advanced Hunting, as you would look them up by hand:

- ``DeviceTvmInfoGathering`` holds what each device last reported, with the signature,
  engine and platform versions and the antivirus mode in its ``AdditionalFields``;
- ``DeviceTvmSecureConfigurationAssessment`` holds the "antivirus definitions up to
  date" check (``scid-2011``), which says whether that signature is current.

The query is built here; running it is the caller's (``GraphClient.hunt`` or
``XdrClient.hunt``), so either Advanced Hunting API will do.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import candidate_names, require_host, short_name

UP_TO_DATE_CHECK = "scid-2011"
# AdditionalFields.AvMode is a number; these are the ones Defender documents.
AV_MODES = {"0": "active", "1": "passive", "4": "EDR block"}

_QUERY = """\
let wanted = dynamic({names});
let versions = DeviceTvmInfoGathering
| where DeviceName in~ (wanted) or tostring(split(DeviceName, ".")[0]) in~ (wanted)
| summarize arg_max(Timestamp, DeviceName, OSPlatform, AdditionalFields) by DeviceId
| extend Fields = todynamic(AdditionalFields)
| project DeviceId, DeviceName, OSPlatform, Reported = Timestamp,
    AvSignatureVersion = tostring(Fields.AvSignatureVersion),
    AvEngineVersion = tostring(Fields.AvEngineVersion),
    AvPlatformVersion = tostring(Fields.AvPlatformVersion),
    AvMode = tostring(Fields.AvMode);
let freshness = DeviceTvmSecureConfigurationAssessment
| where ConfigurationId == "{check}"
| where DeviceName in~ (wanted) or tostring(split(DeviceName, ".")[0]) in~ (wanted)
| summarize arg_max(Timestamp, IsCompliant, IsApplicable, Context) by DeviceId
| project DeviceId, SignatureUpToDate = iff(IsApplicable, IsCompliant, bool(null)),
    AssessmentContext = tostring(Context);
versions
| join kind=leftouter freshness on DeviceId
| project-away DeviceId1
| order by DeviceName asc"""


@dataclass(frozen=True)
class AvStatus:
    """One device's antivirus versions, as Advanced Hunting last saw them.

    ``found`` is False for a name Advanced Hunting had nothing for; ``up_to_date`` is
    None when the definitions check does not apply or has not run.
    """

    query: str
    found: bool
    device_id: str = ""
    device_name: str = ""
    os_platform: str = ""
    signature: str = ""
    engine: str = ""
    platform: str = ""
    mode: str = ""
    up_to_date: bool | None = None
    reported: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def older_than(self, minimum: str) -> bool:
        """True when the signature is below ``minimum`` (or unknown)."""
        return not self.signature or version_key(self.signature) < version_key(minimum)


def av_query(names: Sequence[str]) -> str:
    """The KQL for ``names``: each device's FQDN and short name are both looked for."""
    wanted: list[str] = []
    for name in names:
        wanted.extend(candidate_names(require_host(name)))
    if not wanted:
        raise InputError("no devices named")
    unique = list(dict.fromkeys(item.lower() for item in wanted))
    return _QUERY.format(names=json.dumps(unique), check=UP_TO_DATE_CHECK)


def av_statuses(names: Iterable[str], result: QueryResult) -> list[AvStatus]:
    """One status per name asked for, in order, matched on the FQDN or short name.

    A name that matches several devices (stale records keep a name) gives one status
    for each, newest report first.
    """
    rows = [dict(row) for row in result.rows]
    statuses: list[AvStatus] = []
    for name in names:
        full = name.strip().rstrip(".").lower()
        short = short_name(full).lower()
        matched = [
            row
            for row in rows
            if fields.text(row, "DeviceName").lower() in {full, short}
            or short_name(fields.text(row, "DeviceName")).lower() == short
        ]
        if not matched:
            statuses.append(AvStatus(query=name, found=False))
            continue
        matched.sort(key=lambda row: fields.text(row, "Reported"), reverse=True)
        statuses.extend(_status(name, row) for row in matched)
    return statuses


def version_key(version: str) -> tuple[int, ...]:
    """``1.419.123.0`` -> (1, 419, 123, 0), for comparing versions numerically."""
    parts = re.findall(r"\d+", version)
    if not parts:
        raise InputError(f"{version!r} is not a version number")
    return tuple(int(part) for part in parts)


def mode_label(value: object) -> str:
    """``0`` -> ``active``; an unknown mode is kept as it came."""
    text = "" if value is None else str(value).strip()
    return AV_MODES.get(text, text)


def _status(query: str, row: Mapping[str, Any]) -> AvStatus:
    up_to_date = row.get("SignatureUpToDate")
    return AvStatus(
        query=query,
        found=True,
        device_id=fields.text(row, "DeviceId"),
        device_name=fields.text(row, "DeviceName"),
        os_platform=fields.text(row, "OSPlatform"),
        signature=fields.text(row, "AvSignatureVersion"),
        engine=fields.text(row, "AvEngineVersion"),
        platform=fields.text(row, "AvPlatformVersion"),
        mode=mode_label(row.get("AvMode")),
        up_to_date=up_to_date if isinstance(up_to_date, bool) else None,
        reported=fields.when(row, "Reported"),
        raw=dict(row),
    )
