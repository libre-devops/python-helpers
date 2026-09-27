"""Confluence's records as this package reads them: spaces, pages and search results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from libre_devops_helpers.core import fields


def _link(site: str, data: Mapping[str, Any]) -> str:
    webui = fields.text(fields.mapping(data.get("_links")), "webui")
    return f"{site}/wiki{webui}" if webui else ""


@dataclass(frozen=True)
class Space:
    """One Confluence space."""

    id: str
    key: str
    name: str
    type: str
    status: str
    url: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any], site: str) -> Space:
        """A space from Confluence's JSON (v2); ``site`` makes its link."""
        return cls(
            id=fields.text(data, "id"),
            key=fields.text(data, "key"),
            name=fields.text(data, "name"),
            type=fields.text(data, "type"),
            status=fields.text(data, "status"),
            url=_link(site, data),
        )


@dataclass(frozen=True)
class Page:
    """One page: its title, where it is, its version, and its body as Markdown when read."""

    id: str
    title: str
    space_id: str
    status: str
    version: int
    updated: datetime | None
    url: str
    body: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any], site: str, body: str = "") -> Page:
        """A page from Confluence's JSON (v2); ``site`` makes its link."""
        version = fields.mapping(data.get("version"))
        number = fields.number(version.get("number"))
        return cls(
            id=fields.text(data, "id"),
            title=fields.text(data, "title"),
            space_id=fields.text(data, "spaceId"),
            status=fields.text(data, "status"),
            version=int(number) if number is not None else 0,
            updated=fields.when(version, "createdAt"),
            url=_link(site, data),
            body=body,
        )


@dataclass(frozen=True)
class SearchHit:
    """One thing a CQL search found: a page, a blog post, an attachment, a space."""

    id: str
    type: str
    title: str
    space: str
    updated: datetime | None
    url: str
    excerpt: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any], site: str) -> SearchHit:
        """A result from Confluence's search (v1); ``site`` makes its link."""
        content = fields.mapping(data.get("content"))
        path = fields.text(data, "url")
        return cls(
            id=fields.text(content, "id"),
            type=fields.text(content, "type") or fields.text(data, "entityType"),
            title=fields.text(data, "title") or fields.text(content, "title"),
            space=fields.text(fields.mapping(data.get("resultGlobalContainer")), "title"),
            updated=fields.when(data, "lastModified"),
            url=f"{site}/wiki{path}" if path else "",
            excerpt=" ".join(fields.text(data, "excerpt").split()),
        )
