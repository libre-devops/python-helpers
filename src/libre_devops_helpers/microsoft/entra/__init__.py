"""Entra ID through Microsoft Graph: devices, users, groups, roles, sign-ins, apps and policies.

Depends only on ``core`` and the shared Microsoft layer. Public API::

    from libre_devops_helpers.microsoft.auth import AzureCliCredential
    from libre_devops_helpers.microsoft.entra import EntraClient

    with EntraClient.create(AzureCliCredential(), tenant_id) as entra:
        for device in entra.find_devices("web01.corp.example.com"):
            groups = entra.device_groups(device)
"""

from libre_devops_helpers.microsoft.entra.client import EntraClient, MemberKind, expiring
from libre_devops_helpers.microsoft.entra.models import (
    AppCredential,
    ConditionalAccessPolicy,
    DeviceLookup,
    DirectoryObject,
    EntraDevice,
    EntraGroup,
    EntraUser,
    RoleAssignment,
    RoleReport,
    SignIn,
)
from libre_devops_helpers.microsoft.entra.permissions import REQUIREMENTS

__all__ = [
    "REQUIREMENTS",
    "AppCredential",
    "ConditionalAccessPolicy",
    "DeviceLookup",
    "DirectoryObject",
    "EntraClient",
    "EntraDevice",
    "EntraGroup",
    "EntraUser",
    "MemberKind",
    "RoleAssignment",
    "RoleReport",
    "SignIn",
    "expiring",
]
