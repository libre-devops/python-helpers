"""ServiceNow: sign-in, the Table API, and features built on them.

Laid out like the Microsoft package: this shared layer (``config``, ``auth``, ``tables``,
``roles``) depends on ``core`` only, and each feature (``instance``) on this layer.

Public API::

    from libre_devops_helpers.servicenow import TableClient, credential_for, load_config
"""

from libre_devops_helpers.servicenow.auth import (
    BasicCredential,
    Credential,
    OAuthApp,
    OAuthCredential,
    credential_for,
)
from libre_devops_helpers.servicenow.config import (
    AUTH_METHODS,
    CONFIG_TEMPLATE,
    SECTION,
    SIGN_INS,
    Profile,
    ServiceNowConfig,
    from_file,
    load_config,
    profile_from_env,
)
from libre_devops_helpers.servicenow.roles import RoleRequirement
from libre_devops_helpers.servicenow.tables import TableClient, condition

__all__ = [
    "AUTH_METHODS",
    "CONFIG_TEMPLATE",
    "SECTION",
    "SIGN_INS",
    "BasicCredential",
    "Credential",
    "OAuthApp",
    "OAuthCredential",
    "Profile",
    "RoleRequirement",
    "ServiceNowConfig",
    "TableClient",
    "condition",
    "credential_for",
    "from_file",
    "load_config",
    "profile_from_env",
]
