"""Defender XDR incidents, through the Graph security API, Sentinel's included.

In the unified security operations platform, Microsoft Sentinel's incidents land in the
same queue as Defender's; each alert's ``serviceSource`` says where it came from.

Public API::

    from libre_devops_helpers.microsoft.incidents import IncidentsClient

    found = IncidentsClient.for_profile(profile, tokens).incidents(statuses=OPEN_STATUSES)
"""

from libre_devops_helpers.microsoft.incidents.client import (
    MAX_INCIDENTS,
    IncidentList,
    IncidentsClient,
    Summary,
    most_severe,
    newest,
    severities_from,
    summarise,
)
from libre_devops_helpers.microsoft.incidents.models import (
    OPEN_STATUSES,
    SEVERITY_ORDER,
    SOURCES,
    STATUSES,
    Incident,
    IncidentAlert,
    severity_rank,
)
from libre_devops_helpers.microsoft.incidents.permissions import REQUIREMENTS

__all__ = [
    "MAX_INCIDENTS",
    "OPEN_STATUSES",
    "REQUIREMENTS",
    "SEVERITY_ORDER",
    "SOURCES",
    "STATUSES",
    "Incident",
    "IncidentAlert",
    "IncidentList",
    "IncidentsClient",
    "Summary",
    "most_severe",
    "newest",
    "severities_from",
    "severity_rank",
    "summarise",
]
