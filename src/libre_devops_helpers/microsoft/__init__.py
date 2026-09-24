"""Microsoft: Azure, Entra ID, Defender, Intune, Key Vault and Log Analytics.

This package is the Microsoft vendor layer. Its top-level modules are shared by every
Microsoft feature: clouds and their endpoints, the APIs as tokens see them, token checks,
credentials, the Azure CLI runner and the ``[microsoft]`` profiles. The feature modules
(``azcli``, ``entra``, ``xdr``, ``intune``, ``azure``, ``keyvault``, ``loganalytics``)
depend on those and on ``core`` only; ``devices`` combines ``entra``, ``xdr`` and
``intune``.

Public API::

    from libre_devops_helpers.core import CachingTokenProvider
    from libre_devops_helpers.microsoft import credential_for, load_config
    from libre_devops_helpers.microsoft.entra import EntraClient

    profile = load_config().get("prod-tenant")
    tokens = CachingTokenProvider(credential_for(profile))
"""

from libre_devops_helpers.microsoft.auth import (
    AzureCliCredential,
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
    credential_for,
)
from libre_devops_helpers.microsoft.clouds import CHINA, CLOUDS, PUBLIC, USGOV, Cloud, get_cloud
from libre_devops_helpers.microsoft.config import (
    AUTH_METHODS,
    CONFIG_TEMPLATE,
    PLACEHOLDER_ID,
    MicrosoftConfig,
    Profile,
    load_config,
    parse_config,
)
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner
from libre_devops_helpers.microsoft.resources import (
    ARM,
    GRAPH,
    KEY_VAULT,
    LOG_ANALYTICS,
    MDE,
    RESOURCES,
    Requirement,
    Resource,
    resolve_resource,
    resources_for,
)
from libre_devops_helpers.microsoft.tokens import (
    Check,
    DecodedToken,
    decode_token,
    passed,
    validate_token,
)

__all__ = [
    "ARM",
    "AUTH_METHODS",
    "CHINA",
    "CLOUDS",
    "CONFIG_TEMPLATE",
    "GRAPH",
    "KEY_VAULT",
    "LOG_ANALYTICS",
    "MDE",
    "PLACEHOLDER_ID",
    "PUBLIC",
    "RESOURCES",
    "USGOV",
    "AzCliError",
    "AzureCliCredential",
    "AzureCliRunner",
    "Check",
    "ClientSecretCredential",
    "Cloud",
    "DecodedToken",
    "ManagedIdentityCredential",
    "MicrosoftConfig",
    "Profile",
    "Requirement",
    "Resource",
    "WorkloadIdentityCredential",
    "credential_for",
    "decode_token",
    "get_cloud",
    "load_config",
    "parse_config",
    "passed",
    "resolve_resource",
    "resources_for",
    "validate_token",
]
