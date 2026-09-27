"""Confluence Cloud, through its REST API: spaces and pages (v2), and CQL search (v1)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from libre_devops_helpers.atlassian.client import AtlassianServiceClient
from libre_devops_helpers.atlassian.confluence.models import Page, SearchHit, Space
from libre_devops_helpers.core.errors import InputError, NotFoundError
from libre_devops_helpers.core.markdown import html_to_markdown

_PAGE_ID = re.compile(r"[1-9][0-9]{0,19}")
# A space's key, or a personal space's: ~ and the account's id.
_SPACE_KEY = re.compile(r"[A-Za-z0-9_]{1,255}|~[A-Za-z0-9_:-]{1,128}")


class ConfluenceClient(AtlassianServiceClient):
    """Reads one site's Confluence as one account. Close it when done."""

    NAME = "Confluence"

    @property
    def site(self) -> str:
        """The site's address, for links."""
        return self.api.base_url

    def spaces(self) -> list[Space]:
        """Every space the account can see."""
        items = self._pages("/wiki/api/v2/spaces", {"limit": "250"})
        return [Space.from_api(item, self.site) for item in items]

    def space(self, key: str) -> Space:
        """The space called ``key``, or a NotFoundError."""
        wanted = key.strip()
        if not _SPACE_KEY.fullmatch(wanted):
            raise InputError(f"{key!r} is not a space key", hint="e.g. OPS, or ~ and an id")
        found = self.api.get("/wiki/api/v2/spaces", params={"keys": wanted}).get("results", [])
        if not found:
            raise NotFoundError(f"no space {wanted!r} that this account can see")
        return Space.from_api(found[0], self.site)

    def pages(
        self, *, space: str | None = None, title: str | None = None, limit: int = 50
    ) -> list[Page]:
        """Pages, newest change first: in ``space`` (its key) and called ``title``, if given."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        params = {"limit": str(min(limit, 250)), "sort": "-modified-date"}
        if title:
            params["title"] = title
        path = "/wiki/api/v2/pages"
        if space:
            path = f"/wiki/api/v2/spaces/{self.space(space).id}/pages"
        found: list[Page] = []
        for item in self._pages(path, params):
            found.append(Page.from_api(item, self.site))
            if len(found) >= limit:
                break
        return found

    def page(self, page_id: str) -> Page:
        """One page, with its body as Markdown."""
        wanted = page_id.strip()
        if not _PAGE_ID.fullmatch(wanted):
            raise InputError(f"{page_id!r} is not a page id", hint="the number in its link")
        data = self.api.get(f"/wiki/api/v2/pages/{wanted}", params={"body-format": "storage"})
        storage = (
            data.get("body", {}).get("storage", {}) if isinstance(data.get("body"), dict) else {}
        )
        html = storage.get("value") if isinstance(storage, dict) else None
        body = html_to_markdown(html) if isinstance(html, str) and html else ""
        return Page.from_api(data, self.site, body.strip())

    def search(self, cql: str, *, limit: int = 25) -> list[SearchHit]:
        """What the CQL query ``cql`` finds, up to ``limit``."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        found: list[SearchHit] = []
        params = {"cql": cql, "limit": str(min(limit, 100))}
        for item in self._pages("/wiki/rest/api/search", params):
            found.append(SearchHit.from_api(item, self.site))
            if len(found) >= limit:
                break
        return found

    def _pages(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
        """Every item of a paged list: Confluence's ``_links.next`` is a path on the site."""
        page = self.api.get(path, params=params)
        while True:
            yield from page.get("results", [])
            following = (page.get("_links") or {}).get("next")
            if not isinstance(following, str) or not following.startswith("/"):
                return
            page = self.api.get(following)
