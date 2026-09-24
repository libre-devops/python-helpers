"""Defender for Endpoint (Defender XDR): machines, alerts, vulnerabilities, indicators, hunting.

Depends only on ``core`` and the shared Microsoft layer. Public API::

    from libre_devops_helpers.microsoft.auth import AzureCliCredential
    from libre_devops_helpers.microsoft.xdr import XdrClient

    with XdrClient.create(AzureCliCredential(), tenant_id) as xdr:
        lookup = xdr.find_machine("web01.corp.example.com")
        if lookup.machine:
            print(lookup.machine.onboarding_status, lookup.machine.health_status)
"""

from libre_devops_helpers.microsoft.xdr.client import XdrClient, parse_severity
from libre_devops_helpers.microsoft.xdr.models import (
    Alert,
    Indicator,
    Machine,
    MachineLookup,
    Vulnerability,
)
from libre_devops_helpers.microsoft.xdr.permissions import REQUIREMENTS

__all__ = [
    "REQUIREMENTS",
    "Alert",
    "Indicator",
    "Machine",
    "MachineLookup",
    "Vulnerability",
    "XdrClient",
    "parse_severity",
]
