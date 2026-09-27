"""Jira's records as this package reads them: issues and projects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields


@dataclass(frozen=True)
class Issue:
    """One Jira issue: its key, what it is, where it stands, and who has it."""

    key: str
    id: str
    summary: str
    type: str
    status: str
    status_category: str  # To Do, In Progress or Done, as Jira groups every status
    priority: str
    assignee: str
    reporter: str
    project: str
    labels: tuple[str, ...]
    created: datetime | None
    updated: datetime | None
    url: str
    description: str = ""  # Markdown, when the issue was read on its own
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any], site: str, description: str = "") -> Issue:
        """An issue from Jira's JSON; ``site`` makes its link."""
        found = fields.mapping(data.get("fields"))
        status = fields.mapping(found.get("status"))
        key = fields.text(data, "key")
        return cls(
            key=key,
            id=fields.text(data, "id"),
            summary=fields.text(found, "summary"),
            type=fields.text(fields.mapping(found.get("issuetype")), "name"),
            status=fields.text(status, "name"),
            status_category=fields.text(fields.mapping(status.get("statusCategory")), "name"),
            priority=fields.text(fields.mapping(found.get("priority")), "name"),
            assignee=fields.text(fields.mapping(found.get("assignee")), "displayName"),
            reporter=fields.text(fields.mapping(found.get("reporter")), "displayName"),
            project=fields.text(fields.mapping(found.get("project")), "key"),
            labels=tuple(str(label) for label in fields.items(found.get("labels"))),
            created=fields.when(found, "created"),
            updated=fields.when(found, "updated"),
            url=f"{site}/browse/{key}",
            description=description,
            raw=data,
        )


@dataclass(frozen=True)
class Project:
    """One Jira project."""

    key: str
    id: str
    name: str
    type: str
    url: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any], site: str) -> Project:
        """A project from Jira's JSON; ``site`` makes its link."""
        key = fields.text(data, "key")
        return cls(
            key=key,
            id=fields.text(data, "id"),
            name=fields.text(data, "name"),
            type=fields.text(data, "projectTypeKey"),
            url=f"{site}/browse/{key}",
        )
