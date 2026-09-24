"""Switch the Azure CLI's active account between configured profiles.

The Azure CLI keeps one active account per user (in ``~/.azure``), so a switch
applies to every shell at once. The Entra and XDR helpers do not rely on it:
they request tokens with an explicit ``--tenant``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from libre_devops_helpers.microsoft.azcli.client import Account, AzCli
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.process import AzCliError


@dataclass(frozen=True)
class SwitchResult:
    """What ``switch_profile`` did."""

    profile: Profile
    account: Account
    signed_in: bool


def find_account(accounts: Iterable[Account], profile: Profile) -> Account | None:
    """The account that satisfies ``profile``, or None when the CLI has none.

    A subscription profile needs that exact subscription in its tenant. A tenant
    profile takes any account in the tenant, preferring the one already active
    (so switching does not needlessly move off a subscription), then the
    tenant-level entry, then any enabled subscription.
    """
    in_tenant = [account for account in accounts if account.tenant_id == profile.tenant_id]
    if profile.subscription_id:
        return next((a for a in in_tenant if a.id == profile.subscription_id), None)
    for preferred in (
        lambda a: a.is_default,
        lambda a: a.tenant_level,
        lambda a: a.state == "Enabled",
    ):
        match = next((a for a in in_tenant if preferred(a)), None)
        if match is not None:
            return match
    return in_tenant[0] if in_tenant else None


def match_profile(profiles: Iterable[Profile], account: Account) -> Profile | None:
    """The profile describing ``account``: a subscription match first, then a tenant match."""
    candidates = list(profiles)
    for profile in candidates:
        if profile.subscription_id == account.id and profile.tenant_id == account.tenant_id:
            return profile
    for profile in candidates:
        if profile.subscription_id is None and profile.tenant_id == account.tenant_id:
            return profile
    return None


def switch_profile(
    az: AzCli, profile: Profile, *, sign_in: bool = True, device_code: bool = False
) -> SwitchResult:
    """Make ``profile`` the Azure CLI's active context, signing in first when needed.

    With ``sign_in=False`` a missing session raises instead of prompting, which
    suits scripts. The switch is read back and verified before returning.
    """
    profile.require_real_ids()
    account = find_account(az.accounts(), profile)
    signed_in = False
    if account is None:
        if not sign_in:
            raise AzCliError(
                f"the Azure CLI has no session for profile {profile.name!r}",
                hint=f"sign in with: az login --tenant {profile.tenant_id}",
            )
        az.login(
            profile.tenant_id,
            device_code=device_code,
            allow_no_subscriptions=profile.subscription_id is None,
        )
        signed_in = True
        account = find_account(az.accounts(), profile)
        if account is None:
            raise AzCliError(
                f"signed in to tenant {profile.tenant_id}, but subscription "
                f"{profile.subscription_id} is not visible to that account"
            )

    az.set_account(account.id)
    current = az.current_account()
    if current is None or current.id != account.id:
        raise AzCliError(f"the Azure CLI did not switch to {account.id}")
    return SwitchResult(profile=profile, account=current, signed_in=signed_in)
