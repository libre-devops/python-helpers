"""What each Entra feature needs from a Graph token.

``Directory.AccessAsUser.All`` appears in most groups because the Azure CLI's delegated
Graph token carries it, and it lets the call do whatever the signed-in user can.
"""

from libre_devops_helpers.microsoft.resources import Requirement

_DIRECTORY = ("Directory.Read.All", "Directory.ReadWrite.All", "Directory.AccessAsUser.All")

REQUIREMENTS = (
    Requirement("entra devices", "graph", (("Device.Read.All", *_DIRECTORY),)),
    Requirement(
        "entra groups",
        "graph",
        (("GroupMember.Read.All", "Group.Read.All", "Group.ReadWrite.All", *_DIRECTORY),),
    ),
    Requirement("entra users", "graph", (("User.Read.All", "User.ReadWrite.All", *_DIRECTORY),)),
    # Active roles are read through the user's memberships, which directory read covers.
    Requirement(
        "entra roles",
        "graph",
        (("RoleManagement.Read.Directory", "RoleManagement.Read.All", *_DIRECTORY),),
    ),
    # PIM eligibility is not covered by directory read, not even Directory.AccessAsUser.All.
    Requirement(
        "entra pim eligibility",
        "graph",
        (
            (
                "RoleEligibilitySchedule.Read.Directory",
                "RoleEligibilitySchedule.ReadWrite.Directory",
                "RoleManagement.Read.Directory",
                "RoleManagement.Read.All",
                "RoleManagement.ReadWrite.Directory",
            ),
        ),
    ),
    Requirement(
        "entra apps",
        "graph",
        (("Application.Read.All", "Application.ReadWrite.All", *_DIRECTORY),),
    ),
    # Graph asks for both: the audit log itself, and directory read to resolve names.
    Requirement("entra sign-ins", "graph", (("AuditLog.Read.All",), _DIRECTORY)),
    Requirement(
        "entra conditional access",
        "graph",
        (("Policy.Read.All", "Policy.ReadWrite.ConditionalAccess"),),
    ),
)
