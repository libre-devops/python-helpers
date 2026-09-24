"""The instance itself: the signed-in user and roles, the release, and applications.

Public API::

    from libre_devops_helpers.servicenow.instance import InstanceClient

    InstanceClient(tables).current_user("admin")
"""

from libre_devops_helpers.servicenow.instance.client import (
    SIR_PLUGIN,
    SIR_SCOPE,
    SIR_TABLE,
    InstanceClient,
)
from libre_devops_helpers.servicenow.instance.models import Application, AppStatus, Release, User
from libre_devops_helpers.servicenow.roles import RoleRequirement

# Reading applications and system properties takes admin on a default instance.
REQUIREMENTS = (RoleRequirement("instance release and applications", ("admin",)),)

__all__ = [
    "REQUIREMENTS",
    "SIR_PLUGIN",
    "SIR_SCOPE",
    "SIR_TABLE",
    "AppStatus",
    "Application",
    "InstanceClient",
    "Release",
    "User",
]
