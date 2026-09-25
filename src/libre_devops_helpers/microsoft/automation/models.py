"""Azure Automation accounts, the jobs their runbooks ran, and each job's log streams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.microsoft.resource_ids import try_parse_resource_id

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
        """An Automation account as ARM returns it; its subscription and resource group come from
        its id."""
        resource_id = fields.text(data, "id")
        parsed = try_parse_resource_id(resource_id)
        return cls(
            id=resource_id,
            name=fields.text(data, "name"),
            subscription_id=parsed.subscription if parsed else "",
            resource_group=parsed.resource_group if parsed else "",
            location=fields.text(data, "location"),
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
        """A job as ARM lists it."""
        props = fields.mapping(data.get("properties"))
        runbook = props.get("runbook")
        return cls(
            # The job's resource name is its id: the one the portal shows.
            id=(fields.text(data, "name") or fields.text(props, "jobId")),
            runbook=fields.text(runbook, "name") if isinstance(runbook, Mapping) else "",
            status=fields.text(props, "status"),
            created=fields.when(props, "creationTime"),
            started=fields.when(props, "startTime"),
            ended=fields.when(props, "endTime"),
            # Empty for Azure's own sandboxes; a Hybrid Runbook Worker group's name otherwise.
            run_on=fields.text(props, "runOn"),
            started_by=fields.text(props, "startedBy"),
            exception=fields.text(props, "exception"),
            raw=dict(data),
        )

    @property
    def failed(self) -> bool:
        """Whether the job failed, was stopped or was suspended."""
        return self.status in FAILED

    @property
    def finished(self) -> bool:
        """Whether the job has ended, however it ended."""
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
        """A job stream record: from a listing, only its summary; read singly, its full text."""
        props = fields.mapping(data.get("properties"))
        return cls(
            id=fields.text(props, "jobStreamId"),
            time=fields.when(props, "time"),
            stream=fields.text(props, "streamType"),
            summary=fields.text(props, "summary"),
            # Only a single stream's GET carries the full text; a listing has the summary.
            text=fields.text(props, "streamText"),
            raw=dict(data),
        )

    @property
    def message(self) -> str:
        """The record's full text when it was read singly, else its summary."""
        return self.text or self.summary
