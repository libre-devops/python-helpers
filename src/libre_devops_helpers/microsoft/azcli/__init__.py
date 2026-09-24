"""Azure CLI context: accounts, sign-in and switching the active account between profiles.

Tokens from the Azure CLI come from ``core.auth.AzureCliCredential``, not from here.

Public API::

    from libre_devops_helpers.microsoft.azcli import AzCli, switch_profile

    result = switch_profile(AzCli(), profile)
"""

from libre_devops_helpers.microsoft.azcli.client import Account, AzCli
from libre_devops_helpers.microsoft.azcli.context import (
    SwitchResult,
    find_account,
    match_profile,
    switch_profile,
)

__all__ = [
    "Account",
    "AzCli",
    "SwitchResult",
    "find_account",
    "match_profile",
    "switch_profile",
]
