"""What each PIM feature needs from a Graph token, as Graph itself reports it.

Graph asks for a ReadWrite scope even to list requests. PIM for Azure resources goes
through ARM and rests on Azure RBAC instead, so it has no requirements here.
"""

from libre_devops_helpers.microsoft.resources import Requirement

_ROLE_MANAGEMENT = (
    "RoleManagement.Read.Directory",
    "RoleManagement.Read.All",
    "RoleManagement.ReadWrite.Directory",
)

REQUIREMENTS = (
    Requirement(
        "pim entra eligible",
        "graph",
        (
            (
                "RoleEligibilitySchedule.Read.Directory",
                "RoleEligibilitySchedule.ReadWrite.Directory",
                *_ROLE_MANAGEMENT,
            ),
        ),
    ),
    Requirement(
        "pim entra active",
        "graph",
        (
            (
                "RoleAssignmentSchedule.Read.Directory",
                "RoleAssignmentSchedule.ReadWrite.Directory",
                *_ROLE_MANAGEMENT,
            ),
        ),
    ),
    Requirement(
        "pim entra requests",
        "graph",
        (("RoleAssignmentSchedule.ReadWrite.Directory", "RoleManagement.ReadWrite.Directory"),),
    ),
    Requirement(
        "pim entra settings",
        "graph",
        (
            (
                "RoleManagementPolicy.Read.Directory",
                "RoleManagementPolicy.ReadWrite.Directory",
                *_ROLE_MANAGEMENT,
            ),
        ),
    ),
    Requirement(
        "pim groups eligible",
        "graph",
        (
            (
                "PrivilegedEligibilitySchedule.Read.AzureADGroup",
                "PrivilegedEligibilitySchedule.ReadWrite.AzureADGroup",
                "PrivilegedAccess.Read.AzureADGroup",
                "PrivilegedAccess.ReadWrite.AzureADGroup",
            ),
        ),
    ),
    Requirement(
        "pim groups active",
        "graph",
        (
            (
                "PrivilegedAssignmentSchedule.Read.AzureADGroup",
                "PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup",
                "PrivilegedAccess.Read.AzureADGroup",
                "PrivilegedAccess.ReadWrite.AzureADGroup",
            ),
        ),
    ),
    Requirement(
        "pim groups requests",
        "graph",
        (
            (
                "PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup",
                "PrivilegedAccess.ReadWrite.AzureADGroup",
            ),
        ),
    ),
    Requirement(
        "pim groups settings",
        "graph",
        (
            (
                "RoleManagementPolicy.Read.AzureADGroup",
                "RoleManagementPolicy.ReadWrite.AzureADGroup",
            ),
        ),
    ),
)
