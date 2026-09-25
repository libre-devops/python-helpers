"""Log Analytics: run KQL against a workspace (Sentinel workspaces included), and see which
tables it is receiving (``ingestion``).

Depends only on ``core`` and the shared Microsoft layer. Access rests on Azure RBAC on
the workspace, so there are no token scope requirements to declare. Public API::

    from libre_devops_helpers.microsoft.loganalytics import LogAnalyticsClient

    with LogAnalyticsClient.for_profile(profile, tokens) as logs:
        result = logs.query(workspace_id, "Heartbeat | summarize count() by Computer")
"""

from libre_devops_helpers.microsoft.loganalytics.client import LogAnalyticsClient
from libre_devops_helpers.microsoft.loganalytics.ingestion import (
    DEFAULT_QUIET_AFTER,
    DEFAULT_WINDOW,
    TableIngestion,
    by_quietest,
    ingestion_query,
    read_ingestion,
)
from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "DEFAULT_QUIET_AFTER",
    "DEFAULT_WINDOW",
    "REQUIREMENTS",
    "LogAnalyticsClient",
    "TableIngestion",
    "by_quietest",
    "ingestion_query",
    "read_ingestion",
]
