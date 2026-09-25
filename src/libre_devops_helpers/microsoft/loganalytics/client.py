"""Run KQL against a Log Analytics (or Sentinel) workspace through the query API.

Access rests on Azure RBAC on the workspace (Log Analytics Reader is enough), not on
token scopes. The workspace is named by its Workspace ID (a GUID, on its Overview page),
not by its resource id: ``microsoft.azure`` looks one up from the other.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import requests

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.core.http import ApiClient, ServiceClient
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import require_guid
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.resource_ids import looks_like_resource_id


class LogAnalyticsClient(ServiceClient):
    """Log Analytics queries. Close it (or use ``with``) when done."""

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        api_url: str = PUBLIC.log_analytics_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> LogAnalyticsClient:
        """A client for ``tenant_id`` that takes its tokens from ``tokens``."""
        api = ApiClient(
            api_url,
            token_source(tokens, api_url, tenant_id),
            name="Log Analytics",
            verify=verify,
            session=session,
            # A query can legitimately run for minutes; the server caps it at 10.
            timeout=600.0,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> LogAnalyticsClient:
        """A client for a configured profile's tenant, in the profile's cloud."""
        return cls.create(
            tokens,
            profile.tenant_id,
            api_url=profile.cloud.log_analytics_url,
            verify=verify,
            session=session,
        )

    def query(
        self, workspace_id: str, query: str, *, timespan: timedelta | None = None
    ) -> QueryResult:
        """Run ``query`` and return its first table.

        ``timespan`` bounds the query from now backwards, on top of any time filter in
        the query itself. A partial result comes back with the service's error in
        ``warnings`` rather than failing.
        """
        if looks_like_resource_id(workspace_id):
            raise InputError(
                f"that is the workspace's resource id (an ARM id), not its Workspace ID: "
                f"{workspace_id.strip()!r}",
                hint="the query API wants the Workspace ID, a GUID on the workspace's Overview "
                "page; AzureClient.workspace() looks it up from the resource id",
            )
        workspace_id = require_guid(
            workspace_id,
            "a Log Analytics Workspace ID",
            hint="use the workspace's Workspace ID, a GUID on its Overview page",
        )
        if not query.strip():
            raise InputError("the Log Analytics query is empty")
        body: dict[str, Any] = {"query": query}
        if timespan is not None:
            body["timespan"] = f"PT{int(timespan.total_seconds())}S"
        data = self.api.post(f"/v1/workspaces/{workspace_id.strip().lower()}/query", body)
        tables = data.get("tables")
        warnings: list[str] = []
        error = data.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "partial result")
            if not isinstance(tables, list) or not tables:
                raise ApiError(f"Log Analytics: {detail}", code=fields.text(error, "code"))
            warnings.append(detail)
        if not isinstance(tables, list) or not tables or not isinstance(tables[0], dict):
            return QueryResult((), (), warnings=tuple(warnings))
        table = tables[0]
        columns = [
            str(column.get("name"))
            for column in table.get("columns") or []
            if isinstance(column, dict)
        ]
        rows = [row for row in table.get("rows") or [] if isinstance(row, list)]
        result = QueryResult.from_columns(columns, rows)
        return QueryResult(result.columns, result.rows, warnings=tuple(warnings))
