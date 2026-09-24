"""Azure Resource Manager: subscriptions, Resource Graph, RBAC and Defender for Cloud.

Depends only on ``core`` and the shared Microsoft layer. Access rests on Azure RBAC, so
there are no token scope requirements to declare. Public API::

    from libre_devops_helpers.microsoft.azure import AzureClient

    with AzureClient.for_profile(profile, tokens) as azure:
        result = azure.resource_graph("resources | summarize count() by type")
"""

from libre_devops_helpers.microsoft.azure.client import AzureClient
from libre_devops_helpers.microsoft.azure.models import (
    Assessment,
    AzureRoleAssignment,
    DefenderPlan,
    SecureScore,
    SecureScoreControl,
    Subscription,
)
from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "REQUIREMENTS",
    "Assessment",
    "AzureClient",
    "AzureRoleAssignment",
    "DefenderPlan",
    "SecureScore",
    "SecureScoreControl",
    "Subscription",
]
