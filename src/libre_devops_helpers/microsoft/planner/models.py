"""Planner's records as this package reads them: plans, buckets and tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields


@dataclass(frozen=True)
class Plan:
    """One plan: a board of buckets and tasks."""

    id: str
    title: str
    owner: str
    created: datetime | None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Plan:
        """A plan from Graph's JSON."""
        return cls(
            id=fields.text(data, "id"),
            title=fields.text(data, "title"),
            owner=fields.text(data, "owner"),
            created=fields.when(data, "createdDateTime"),
        )


@dataclass(frozen=True)
class Bucket:
    """One column of a plan's board."""

    id: str
    name: str
    plan_id: str

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Bucket:
        """A bucket from Graph's JSON."""
        return cls(
            id=fields.text(data, "id"),
            name=fields.text(data, "name"),
            plan_id=fields.text(data, "planId"),
        )


@dataclass(frozen=True)
class Task:
    """One task: its title, bucket, progress and dates."""

    id: str
    title: str
    plan_id: str
    bucket_id: str
    percent_complete: int
    due: datetime | None
    created: datetime | None
    completed: datetime | None
    etag: str = ""  # which version of the task this is: Planner changes one only with it

    @property
    def done(self) -> bool:
        """Whether the task is complete."""
        return self.percent_complete >= 100

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Task:
        """A task from Graph's JSON."""
        percent = fields.number(data.get("percentComplete"))
        return cls(
            id=fields.text(data, "id"),
            title=fields.text(data, "title"),
            plan_id=fields.text(data, "planId"),
            bucket_id=fields.text(data, "bucketId"),
            percent_complete=int(percent) if percent is not None else 0,
            due=fields.when(data, "dueDateTime"),
            created=fields.when(data, "createdDateTime"),
            completed=fields.when(data, "completedDateTime"),
            etag=fields.text(data, "@odata.etag"),
        )
