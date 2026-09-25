"""Azure Automation: accounts, the jobs their runbooks ran, and each job's logs."""

from libre_devops_helpers.microsoft.automation.client import API_VERSION, AutomationClient
from libre_devops_helpers.microsoft.automation.models import (
    FAILED,
    STREAMS,
    AutomationAccount,
    Job,
    JobStream,
)
from libre_devops_helpers.microsoft.resources import Requirement

# ARM tokens carry no scopes to check: Azure RBAC decides (Reader is enough to read jobs).
REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "API_VERSION",
    "FAILED",
    "REQUIREMENTS",
    "STREAMS",
    "AutomationAccount",
    "AutomationClient",
    "Job",
    "JobStream",
]
