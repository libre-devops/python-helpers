"""Azure Automation accounts, the jobs their runbooks ran, and each job's log streams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core.util import parse_datetime

# Job states that need someone to look: the runbook did not finish as it should.
FAILED = frozenset({"Failed", "Suspended", "Stopped", "Blocked"})
# The streams a job writes, as the portal's tabs name them, and as ARM spells them.
STREAMS = {
    "output": "Output",
    "error": "Error",
    "warning": "Warning",
    "verbose": "Verbose",
    "progress": "Progress",
    "debug": "Debug",
}


@dataclass(frozen=True)
class AutomationAccount:
    """An Automation account, and where it lives."""

    id: str
    name: str
    subscription_id: str
    resource_group: str
    location: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> AutomationAccount:
        resource_id = str(data.get("id") or "")
        parts = resource_id.split("/")
        lowered = [part.lower() for part in parts]

        def after(segment: str) -> str:
            return parts[lowered.index(segment) + 1] if segment in lowered[:-1] else ""

        return cls(
            id=resource_id,
            name=str(data.get("name") or ""),
            subscription_id=after("subscriptions"),
            resource_group=after("resourcegroups"),
            location=str(data.get("location") or ""),
            raw=dict(data),
        )

    @property
    def path(self) -> str:
        """The account's ARM path, which every job request starts from."""
        return self.id


@dataclass(frozen=True)
class Job:
    """One run of a runbook."""

    id: str
    runbook: str
    status: str
    created: datetime | None
    started: datetime | None
    ended: datetime | None
    run_on: str
    started_by: str
    exception: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Job:
        properties = data.get("properties")
        props: Mapping[str, Any] = properties if isinstance(properties, Mapping) else {}
        runbook = props.get("runbook")
        return cls(
            # The job's resource name is its id: the one the portal shows.
            id=str(data.get("name") or props.get("jobId") or ""),
            runbook=str(runbook.get("name") or "") if isinstance(runbook, Mapping) else "",
            status=str(props.get("status") or ""),
            created=parse_datetime(props.get("creationTime")),
            started=parse_datetime(props.get("startTime")),
            ended=parse_datetime(props.get("endTime")),
            # Empty for Azure's own sandboxes; a Hybrid Runbook Worker group's name otherwise.
            run_on=str(props.get("runOn") or ""),
            started_by=str(props.get("startedBy") or ""),
            exception=str(props.get("exception") or ""),
            raw=dict(data),
        )

    @property
    def failed(self) -> bool:
        return self.status in FAILED

    @property
    def finished(self) -> bool:
        return self.ended is not None


@dataclass(frozen=True)
class JobStream:
    """One record a job wrote: a line of output, a warning, an error and so on."""

    id: str
    time: datetime | None
    stream: str
    summary: str
    text: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> JobStream:
        properties = data.get("properties")
        props: Mapping[str, Any] = properties if isinstance(properties, Mapping) else {}
        return cls(
            id=str(props.get("jobStreamId") or ""),
            time=parse_datetime(props.get("time")),
            stream=str(props.get("streamType") or ""),
            summary=str(props.get("summary") or ""),
            # Only a single stream's GET carries the full text; a listing has the summary.
            text=str(props.get("streamText") or ""),
            raw=dict(data),
        )

    @property
    def message(self) -> str:
        return self.text or self.summary
