"""The Graph security API's incidents: one queue for Defender XDR and Sentinel.

Graph filters incidents on time, status and severity; which services raised an
incident's alerts (Sentinel, say) is only known from the alerts, so that filter, and
the sorting, happen here. Incidents come with their alerts (``$expand=alerts``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.util import odata_datetime, odata_string
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.incidents.models import (
    SEVERITY_ORDER,
    STATUSES,
    Incident,
    severity_rank,
)

_PATH = "/v1.0/security/incidents"
PAGE_SIZE = 50  # Graph's most per page
MAX_INCIDENTS = 2000  # a runaway guard: narrow the window for more
_EARLIEST = datetime.min.replace(tzinfo=UTC)
SCOPE_HINT = (
    "incidents need SecurityIncident.Read.All on the Graph token, which the Azure CLI's "
    "token never carries: use an interactive or device-code profile whose app has it. "
    "The account also needs a Defender XDR role, such as Security Reader"
)


@dataclass(frozen=True)
class IncidentList:
    """Incidents found, and whether the guard stopped the listing short."""

    incidents: tuple[Incident, ...]
    truncated: bool = False


@dataclass(frozen=True)
class Summary:
    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_source: dict[str, int]


class IncidentsClient:
    """Reads incidents through Microsoft Graph. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        graph_url: str = PUBLIC.graph_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        api = ApiClient(
            graph_url,
            token_source(tokens, graph_url, tenant_id),
            name="Microsoft Graph",
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
    ) -> Self:
        return cls.create(
            tokens,
            profile.tenant_id,
            graph_url=profile.cloud.graph_url,
            verify=verify,
            session=session,
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def incidents(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        by: str = "createdDateTime",
        statuses: Sequence[str] = (),
        severities: Sequence[str] = (),
        sources: Sequence[str] = (),
    ) -> IncidentList:
        """Incidents from ``start`` to ``end`` (on ``by``), with the given statuses and
        severities (any when empty), whose alerts came from any of ``sources``."""
        if by not in {"createdDateTime", "lastUpdateDateTime"}:
            raise InputError(f"incidents can be windowed on created or updated, not {by!r}")
        for status in statuses:
            if status not in STATUSES:
                raise InputError(f"unknown incident status {status!r}")
        params = {"$expand": "alerts", "$top": str(PAGE_SIZE)}
        expression = _filter(start, end, by, statuses, severities)
        if expression:
            params["$filter"] = expression
        found: list[Incident] = []
        truncated = False
        try:
            for record in self.api.get_all(_PATH, params=params):
                if len(found) >= MAX_INCIDENTS:
                    truncated = True
                    break
                found.append(Incident.from_graph(record))
        except ApiError as exc:
            raise _explained(exc) from None
        if sources:
            wanted = set(sources)
            found = [incident for incident in found if wanted & set(incident.sources)]
        return IncidentList(tuple(found), truncated)

    def incident(self, incident_id: str) -> Incident:
        """One incident, with its alerts and their evidence."""
        if not incident_id.strip().isdigit():
            raise InputError(f"{incident_id!r} is not an incident id (they are numbers)")
        try:
            record = self.api.get(f"{_PATH}/{incident_id.strip()}", params={"$expand": "alerts"})
        except ApiError as exc:
            if exc.status == 404:
                raise NotFoundError(f"no incident {incident_id}") from None
            raise _explained(exc) from None
        return Incident.from_graph(record)


def most_severe(incidents: Iterable[Incident]) -> list[Incident]:
    """Most severe first, and newest first within a severity."""
    ordered = newest(incidents)
    return sorted(ordered, key=lambda incident: severity_rank(incident.severity))


def newest(incidents: Iterable[Incident]) -> list[Incident]:
    """Newest first, by when each was created."""
    return sorted(incidents, key=lambda incident: incident.created or _EARLIEST, reverse=True)


def summarise(incidents: Sequence[Incident]) -> Summary:
    """How many, by severity (most severe first), status and source."""
    severities = Counter(incident.severity.lower() or "unknown" for incident in incidents)
    order = [*SEVERITY_ORDER, *sorted(set(severities) - set(SEVERITY_ORDER))]
    sources = Counter(name for incident in incidents for name in incident.source_names)
    return Summary(
        total=len(incidents),
        by_severity={name: severities[name] for name in order if severities[name]},
        by_status=dict(Counter(incident.status for incident in incidents).most_common()),
        by_source=dict(sources.most_common()),
    )


def severities_from(minimum: str) -> tuple[str, ...]:
    """The severities at or above ``minimum``: ``medium`` -> high, medium."""
    level = minimum.strip().lower()
    if level not in SEVERITY_ORDER:
        raise InputError(
            f"unknown severity {minimum!r}", hint=f"use one of {', '.join(SEVERITY_ORDER)}"
        )
    return SEVERITY_ORDER[: SEVERITY_ORDER.index(level) + 1]


def _filter(
    start: datetime | None,
    end: datetime | None,
    by: str,
    statuses: Sequence[str],
    severities: Sequence[str],
) -> str:
    terms: list[str] = []
    if start is not None:
        terms.append(f"{by} ge {odata_datetime(start)}")
    if end is not None:
        terms.append(f"{by} lt {odata_datetime(end)}")
    for field, values in (("status", statuses), ("severity", severities)):
        if values:
            either = " or ".join(f"{field} eq {odata_string(value)}" for value in values)
            terms.append(f"({either})" if len(values) > 1 else either)
    return " and ".join(terms)


def _explained(exc: ApiError) -> ApiError:
    # A suspended service answers 403 too, and its own hint says why better.
    if exc.status in {401, 403} and "suspended" not in str(exc).lower():
        return ApiError(
            str(exc), status=exc.status, code=exc.code, request_id=exc.request_id, hint=SCOPE_HINT
        )
    return exc
