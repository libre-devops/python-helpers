"""Microsoft Graph, directly: any GET, objects by name or id, and Advanced Hunting.

Public API::

    from libre_devops_helpers.microsoft.graph import GraphClient

    page = GraphClient.for_profile(profile, tokens).page("users", params={"$top": "5"})
"""

from libre_devops_helpers.microsoft.graph.client import (
    HUNT_HINT,
    KINDS,
    VERSIONS,
    GraphClient,
    GraphPage,
    graph_path,
    iso_duration,
    not_found,
)
from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "hunting (xdr hunt, xdr timeline, devices av-signature)",
        "graph",
        (("ThreatHunting.Read.All",),),
    ),
)

__all__ = [
    "HUNT_HINT",
    "KINDS",
    "REQUIREMENTS",
    "VERSIONS",
    "GraphClient",
    "GraphPage",
    "graph_path",
    "iso_duration",
    "not_found",
]
