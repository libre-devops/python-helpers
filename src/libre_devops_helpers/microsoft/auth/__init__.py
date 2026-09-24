"""Microsoft credentials: the Azure CLI, app registrations and managed identities.

Every credential satisfies ``core.auth.TokenProvider``; the service modules take any
provider, and ``credential_for`` builds the one a profile's ``auth`` setting names.

Public API::

    from libre_devops_helpers.core.auth import CachingTokenProvider
    from libre_devops_helpers.microsoft.auth import credential_for

    tokens = CachingTokenProvider(credential_for(profile))
"""

from libre_devops_helpers.microsoft.auth.azure_cli import AzureCliCredential, Reauthenticate
from libre_devops_helpers.microsoft.auth.delegated import (
    DeviceCodeCredential,
    InteractiveCredential,
    LoopbackReceiver,
)
from libre_devops_helpers.microsoft.auth.entra import (
    ClientSecretCredential,
    WorkloadIdentityCredential,
    federated_token_file,
    github_actions_assertion,
)
from libre_devops_helpers.microsoft.auth.factory import credential_for
from libre_devops_helpers.microsoft.auth.lapse import lapse_reason
from libre_devops_helpers.microsoft.auth.managed_identity import ManagedIdentityCredential

__all__ = [
    "AzureCliCredential",
    "ClientSecretCredential",
    "DeviceCodeCredential",
    "InteractiveCredential",
    "LoopbackReceiver",
    "ManagedIdentityCredential",
    "Reauthenticate",
    "WorkloadIdentityCredential",
    "credential_for",
    "federated_token_file",
    "github_actions_assertion",
    "lapse_reason",
]
