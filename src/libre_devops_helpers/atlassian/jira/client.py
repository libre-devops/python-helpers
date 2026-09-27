"""Jira Cloud, through its REST API (v3): searching issues, reading one, and projects."""

from __future__ import annotations

import re
from typing import Any

from libre_devops_helpers.atlassian.client import AtlassianServiceClient
from libre_devops_helpers.atlassian.jira.models import Issue, Project
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.markdown import html_to_markdown

# Jira refuses a query with no restriction at all, so none is ever sent without one.
DEFAULT_JQL = "statusCategory != Done ORDER BY updated DESC"
FIELDS = "summary,status,issuetype,priority,assignee,reporter,created,updated,labels,project"
_ISSUE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*")
_PAGE = 100  # the most Jira gives in one page of a search


class JiraClient(AtlassianServiceClient):
    """Reads one site's Jira as one account. Close it when done."""

    NAME = "Jira"

    @property
    def site(self) -> str:
        """The site's address, for links."""
        return self.api.base_url

    def whoami(self) -> dict[str, Any]:
        """The account the token belongs to, as Jira has it."""
        return self.api.get("/rest/api/3/myself")

    def issues(self, jql: str = DEFAULT_JQL, *, limit: int = 50) -> list[Issue]:
        """The issues ``jql`` finds, in its order, up to ``limit``."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        found: list[Issue] = []
        token = ""
        while len(found) < limit:
            params = {
                "jql": jql,
                "fields": FIELDS,
                "maxResults": str(min(_PAGE, limit - len(found))),
            }
            if token:
                params["nextPageToken"] = token
            page = self.api.get("/rest/api/3/search/jql", params=params)
            found += [Issue.from_api(item, self.site) for item in page.get("issues", [])]
            token = str(page.get("nextPageToken") or "")
            if page.get("isLast", True) or not token:
                break
        return found[:limit]

    def issue(self, key: str) -> Issue:
        """One issue, with its description as Markdown."""
        wanted = key.strip().upper()
        if not _ISSUE_KEY.fullmatch(wanted):
            raise InputError(f"{key!r} is not an issue key", hint="e.g. OPS-123")
        data = self.api.get(
            f"/rest/api/3/issue/{wanted}",
            params={"fields": f"{FIELDS},description", "expand": "renderedFields"},
        )
        rendered = data.get("renderedFields") or {}
        html = rendered.get("description") if isinstance(rendered, dict) else None
        description = html_to_markdown(html) if isinstance(html, str) and html else ""
        return Issue.from_api(data, self.site, description.strip())

    def projects(self) -> list[Project]:
        """Every project the account can see."""
        found: list[Project] = []
        start = 0
        while True:
            page = self.api.get(
                "/rest/api/3/project/search", params={"startAt": str(start), "maxResults": "50"}
            )
            values = page.get("values", [])
            found += [Project.from_api(item, self.site) for item in values]
            start += len(values)
            if page.get("isLast", True) or not values:
                return found
