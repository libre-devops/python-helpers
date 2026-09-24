"""Read-only Defender for Endpoint queries: machines, alerts, vulnerabilities, hunting.

Device lookups are small, server-side filtered GETs per candidate name, never a
download of the tenant-wide machine inventory. The FQDN is tried first, then the short
hostname, because Defender does not report Linux names consistently.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import ApiError, LdoError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import (
    candidate_names,
    odata_datetime,
    odata_string,
)
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.xdr.models import (
    Alert,
    Indicator,
    Machine,
    MachineLookup,
    Vulnerability,
)

_MACHINE_ID = re.compile(r"^[0-9a-fA-F]{40}$")
_NEVER = datetime.min.replace(tzinfo=UTC)
_SEVERITY_ORDER = {"informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# The global Defender resource; regional endpoints accept its tokens.
MDE_RESOURCE = PUBLIC.mde_url or "https://api.securitycenter.microsoft.com"


class XdrClient:
    """Defender for Endpoint lookups. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        api_url: str = MDE_RESOURCE,
        resource: str = MDE_RESOURCE,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> XdrClient:
        """A client for ``tenant_id``. ``api_url`` may be a regional Defender endpoint.

        ``resource`` is what tokens are requested for: the cloud's Defender resource,
        which regional endpoints accept too.
        """
        api = ApiClient(
            api_url,
            token_source(tokens, resource, tenant_id),
            name="Defender for Endpoint",
            verify=verify,
            session=session,
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
    ) -> XdrClient:
        """A client for a configured profile's tenant and Defender endpoint."""
        resource = profile.cloud.require_mde()
        return cls.create(
            tokens,
            profile.tenant_id,
            api_url=profile.mde_url or resource,
            resource=resource,
            verify=verify,
            session=session,
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Machines ---------------------------------------------------------------------

    def machines_named(self, name: str) -> list[Machine]:
        """Every machine record whose ``computerDnsName`` equals ``name``."""
        items = self.api.get_all(
            "/api/machines", params={"$filter": f"computerDnsName eq {odata_string(name)}"}
        )
        return [Machine.from_json(item) for item in items]

    def find_machine(self, name: str) -> MachineLookup:
        """Look one device up by FQDN, falling back to its short hostname."""
        for candidate in candidate_names(name):
            records = self.machines_named(candidate)
            if records:
                newest_first = sorted(
                    records, key=lambda machine: machine.last_seen or _NEVER, reverse=True
                )
                return MachineLookup(name, candidate, tuple(newest_first))
        return MachineLookup(name, None)

    def find_machines(self, names: Iterable[str]) -> list[MachineLookup]:
        """``find_machine`` for each name, in order."""
        return [self.find_machine(name) for name in names]

    def get_machine(self, machine_id: str) -> Machine:
        """One machine by its Defender id (40 hex characters)."""
        machine_id = _machine_id(machine_id)
        try:
            return Machine.from_json(self.api.get(f"/api/machines/{machine_id}"))
        except ApiError as exc:
            if exc.status == 404:
                raise NotFoundError(f"no MDE machine has id {machine_id}") from None
            raise

    def stale_machines(
        self, older_than: timedelta, *, now: datetime | None = None
    ) -> list[Machine]:
        """Machines not seen for ``older_than``, longest silent first.

        The filter runs on the server, so only the stale records are downloaded.
        """
        cutoff = (now or datetime.now(UTC)) - older_than
        items = self.api.get_all(
            "/api/machines", params={"$filter": f"lastSeen lt {odata_datetime(cutoff)}"}
        )
        machines = [Machine.from_json(item) for item in items]
        return sorted(machines, key=lambda machine: machine.last_seen or _NEVER)

    # Alerts -----------------------------------------------------------------------

    def alerts(
        self,
        *,
        machine_id: str | None = None,
        since: datetime | None = None,
        min_severity: str | None = None,
        include_resolved: bool = False,
        limit: int = 200,
    ) -> list[Alert]:
        """Alerts for the tenant, or for one machine, newest first.

        The creation-time filter runs on the server; severity and status are filtered
        here, because the API's support for filtering those varies by endpoint.
        """
        if machine_id is not None:
            items = self.api.get_all(f"/api/machines/{_machine_id(machine_id)}/alerts")
        else:
            params = {"$top": str(max(1, min(limit, 10000)))}
            if since is not None:
                params["$filter"] = f"alertCreationTime ge {odata_datetime(since)}"
            items = self.api.get_all("/api/alerts", params=params)
        floor = parse_severity(min_severity) if min_severity else -1
        alerts = [
            alert
            for alert in (Alert.from_json(item) for item in items)
            if (include_resolved or not alert.resolved)
            and _severity_rank(alert.severity) >= floor
            and (since is None or alert.created is None or alert.created >= since)
        ]
        alerts.sort(key=lambda alert: alert.created or _NEVER, reverse=True)
        return list(itertools.islice(alerts, limit))

    # Vulnerabilities --------------------------------------------------------------

    def vulnerabilities(self, machine_id: str) -> list[Vulnerability]:
        """Vulnerabilities on one machine, most severe first."""
        items = self.api.get_all(f"/api/machines/{_machine_id(machine_id)}/vulnerabilities")
        found = [Vulnerability.from_json(item) for item in items]
        return sorted(
            found,
            key=lambda item: (_severity_rank(item.severity), item.cvss or 0.0),
            reverse=True,
        )

    # Indicators -------------------------------------------------------------------

    def indicators(self) -> list[Indicator]:
        """Every custom indicator in the tenant."""
        return [Indicator.from_json(item) for item in self.api.get_all("/api/indicators")]

    # Advanced Hunting -------------------------------------------------------------

    def hunt(self, query: str) -> QueryResult:
        """Run an Advanced Hunting (KQL) query. The API caps results at 100,000 rows."""
        if not query.strip():
            raise LdoError("the hunting query is empty")
        data = self.api.post("/api/advancedqueries/run", {"Query": query})
        schema = data.get("Schema")
        results = data.get("Results")
        columns = (
            [str(column.get("Name")) for column in schema if isinstance(column, dict)]
            if isinstance(schema, list)
            else []
        )
        rows = (
            [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
        )
        if not columns:
            return QueryResult.from_records(rows)
        return QueryResult(tuple(columns), tuple(rows))


def parse_severity(severity: str) -> int:
    """The rank of a severity someone typed. Raises for anything unknown."""
    rank = _SEVERITY_ORDER.get(severity.strip().casefold())
    if rank is None:
        raise LdoError(
            f"unknown severity {severity!r}", hint=f"use one of {', '.join(_SEVERITY_ORDER)}"
        )
    return rank


def _severity_rank(severity: str | None) -> int:
    # Values from the API are ranked leniently: an unknown one sorts below the rest.
    return _SEVERITY_ORDER.get((severity or "").casefold(), -1)


def _machine_id(value: str) -> str:
    machine_id = value.strip()
    if not _MACHINE_ID.match(machine_id):
        raise LdoError(f"not an MDE machine id: {machine_id!r}")
    return machine_id
