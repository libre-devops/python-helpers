"""Microsoft 365 Message Center posts, as Graph's serviceAnnouncement gives them."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields

ADMIN_CENTRE = "https://admin.microsoft.com/#/MessageCenter/:/messages/"
# The services a security team follows, as security-news filters Message Center by them:
# a post for any of these, or for one whose name holds one of them, is a security post.
SECURITY_SERVICES = (
    "Microsoft Defender",
    "Microsoft 365 Defender",
    "Microsoft Sentinel",
    "Microsoft Purview",
    "Microsoft Entra",
    "Microsoft Intune",
)
# A post's id in a task's title, as the task was raised for the post: at the start, as this
# raises them (MC1183010: ...), or in square brackets, as Microsoft's own Message Center sync
# to Planner writes them ([Service] Title [MC1183010]).
MESSAGE_KEY = re.compile(r"(?:^|(?<=\[))(MC[0-9]+)(?![0-9])", re.IGNORECASE)
# Graph's categories, and how they read.
CATEGORIES = {
    "planForChange": "plan for change",
    "stayInformed": "stay informed",
    "preventOrFixIssue": "prevent or fix issue",
}


@dataclass(frozen=True)
class Message:
    """One Message Center post: what changes, for which services, and by when."""

    id: str
    title: str
    category: str
    severity: str
    services: tuple[str, ...]
    tags: tuple[str, ...]
    major: bool
    starts: datetime | None
    ends: datetime | None
    updated: datetime | None
    action_by: datetime | None
    body_html: str

    SELECT = (
        "id,title,category,severity,services,tags,isMajorChange,startDateTime,endDateTime,"
        "lastModifiedDateTime,actionRequiredByDateTime,body"
    )

    @property
    def url(self) -> str:
        """The post in the Microsoft 365 admin centre, which only admins can open."""
        return ADMIN_CENTRE + self.id

    def for_any(self, services: Iterable[str]) -> bool:
        """Whether a service of the post's holds any of ``services`` (ignoring case):
        ``xdr`` finds Microsoft Defender XDR."""
        wanted = [service.casefold() for service in services]
        return any(part in mine.casefold() for mine in self.services for part in wanted)

    @property
    def task_title(self) -> str:
        """The title a Planner task raised for the post has: ``MC1183010: <its title>``."""
        return f"{self.id}: {self.title}"

    @property
    def category_label(self) -> str:
        """The category as it reads: ``plan for change``."""
        return CATEGORIES.get(self.category, self.category)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Message:
        """A post from Graph's JSON."""
        return cls(
            id=fields.text(data, "id"),
            title=fields.text(data, "title"),
            category=fields.text(data, "category"),
            severity=fields.text(data, "severity"),
            services=tuple(str(service) for service in fields.items(data.get("services"))),
            tags=tuple(str(tag) for tag in fields.items(data.get("tags"))),
            major=fields.flag(data.get("isMajorChange")) is True,
            starts=fields.when(data, "startDateTime"),
            ends=fields.when(data, "endDateTime"),
            updated=fields.when(data, "lastModifiedDateTime"),
            action_by=fields.when(data, "actionRequiredByDateTime"),
            body_html=fields.text(fields.mapping(data.get("body")), "content"),
        )
