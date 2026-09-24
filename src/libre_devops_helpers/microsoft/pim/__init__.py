"""Privileged Identity Management: eligible and active roles, requests, approvals, settings.

Covers the three PIM areas in one shape: Azure resource roles (through Azure Resource
Manager), Entra roles and PIM for Groups (through Microsoft Graph). Depends only on
``core`` and the shared Microsoft layer. Every call reads; nothing is activated here.

Public API::

    from libre_devops_helpers.microsoft.pim import AzurePimClient, GraphPimClient

    with AzurePimClient.for_profile(profile, tokens) as azure:
        eligible = azure.eligible()                    # the signed-in user's
    with GraphPimClient.for_profile(profile, tokens) as graph:
        pending = graph.role_requests(approver=True)   # waiting on the signed-in user
"""

from libre_devops_helpers.microsoft.pim.azure import AzurePimClient
from libre_devops_helpers.microsoft.pim.entra import GraphPimClient
from libre_devops_helpers.microsoft.pim.models import (
    AREAS,
    Area,
    PimAssignment,
    PimRequest,
    PimSettings,
)
from libre_devops_helpers.microsoft.pim.permissions import REQUIREMENTS
from libre_devops_helpers.microsoft.pim.rules import settings_from_rules

__all__ = [
    "AREAS",
    "REQUIREMENTS",
    "Area",
    "AzurePimClient",
    "GraphPimClient",
    "PimAssignment",
    "PimRequest",
    "PimSettings",
    "settings_from_rules",
]
