"""The ServiceNow Table API: read records from any table, a page at a time.

Every ServiceNow feature reads through this. It turns the instance's errors into ones
that say what to do: a refused sign-in, a missing role (an ACL), a table whose plugin is
not installed, or a developer instance that is hibernating and answers with a web page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Self

import requests

from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.core.http import ApiClient, ServiceClient

log = logging.getLogger(__name__)

PAGE_SIZE = 1000
HIBERNATING_HINT = (
    "the instance answered with a web page, not JSON: a developer instance may be "
    "hibernating (wake it at developer.servicenow.com), or the address is not an instance"
)
ACL_HINT = "your account lacks a role (an access control) for this table"


def condition(field: str, value: str, operator: str = "=") -> str:
    """One encoded query condition, refusing values that would change the query.

    ``^`` separates conditions in an encoded query, so a value holding one could add
    conditions of its own; such values are refused rather than escaped.
    """
    if any(mark in value for mark in ("^", "\n", "\r")):
        raise InputError(f"{field}: {value!r} cannot be used in a ServiceNow query")
    return f"{field}{operator}{value}"


class TableClient(ServiceClient):
    """Reads records through ``/api/now/table``, for one instance and one sign-in."""

    @classmethod
    def create(
        cls,
        instance: str,
        authorization: Callable[[], str],
        *,
        scheme: str = "Bearer",
        session: requests.Session | None = None,
        verify: bool | str = True,
    ) -> Self:
        """A client for ``instance``, sending ``scheme`` and ``authorization()`` each time."""
        return cls(
            ApiClient(
                instance,
                authorization,
                name="ServiceNow",
                session=session,
                verify=verify,
                auth_scheme=scheme,
            )
        )

    def records(
        self,
        table: str,
        *,
        query: str | None = None,
        fields: Iterable[str] | None = None,
        limit: int | None = None,
        display_value: bool = False,
    ) -> list[dict[str, Any]]:
        """Records of ``table`` matching the encoded ``query``, up to ``limit``."""
        found: list[dict[str, Any]] = []
        params = {
            "sysparm_exclude_reference_link": "true",
            "sysparm_display_value": "true" if display_value else "false",
        }
        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        while True:
            size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(found))
            page = self._get(
                f"/api/now/table/{table}",
                {**params, "sysparm_limit": str(size), "sysparm_offset": str(len(found))},
            )
            rows = page.get("result")
            if not isinstance(rows, list):
                raise ApiError(f"ServiceNow: the {table} response has no result list")
            found.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < size or (limit is not None and len(found) >= limit):
                return found

    def first(
        self, table: str, *, query: str, fields: Iterable[str] | None = None
    ) -> dict[str, Any] | None:
        """The first record matching ``query``, or None."""
        rows = self.records(table, query=query, fields=fields, limit=1)
        return rows[0] if rows else None

    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        try:
            return self.api.get(path, params=params)
        except ApiError as exc:
            raise _explained(exc) from None


def _explained(exc: ApiError) -> ApiError:
    """``exc`` with a hint for the ways a ServiceNow instance says no."""
    text = str(exc)
    hint = exc.hint
    if exc.status == 401:
        hint = (
            "the instance did not accept the sign-in: check the account and its password or "
            "token. ServiceNow blocks basic sign-in to its APIs for interactive accounts "
            "unless they hold the snc_basic_auth_api_access role"
        )
    elif exc.status == 403:
        hint = ACL_HINT
    elif exc.status == 400 and "invalid table" in text.lower():
        hint = "the table does not exist on this instance: its plugin or app is not installed"
    elif exc.status == 200 and "did not return json" in text.lower():
        hint = HIBERNATING_HINT
    return ApiError(text, status=exc.status, code=exc.code, request_id=exc.request_id, hint=hint)
