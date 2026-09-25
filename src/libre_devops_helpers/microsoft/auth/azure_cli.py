"""Tokens from the Azure CLI's own sign-in (``az account get-access-token``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import AccessToken
from libre_devops_helpers.core.errors import ReauthRequired
from libre_devops_helpers.microsoft.auth.lapse import lapse_reason
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner

# Asked when the Azure CLI's sign-in to a tenant has lapsed: (tenant id, reason). It
# returns True once the CLI is signed in again, so the token can be fetched once more.
Reauthenticate = Callable[[str, str], bool]


class AzureCliCredential:
    """A token provider backed by the Azure CLI session of the person running the tool.

    ``--tenant`` is passed explicitly, so this works for any signed-in tenant and does
    not depend on, or change, the CLI's active account.

    The Azure CLI renews tokens from its refresh token by itself. When that has lapsed
    too, ``reauthenticate`` (if given) gets the chance to sign it in again, and the
    token is fetched once more; otherwise, or if it declines, ReauthRequired is raised
    with the reason.
    """

    def __init__(
        self,
        runner: AzureCliRunner | None = None,
        *,
        reauthenticate: Reauthenticate | None = None,
    ) -> None:
        self._runner = runner or AzureCliRunner()
        self._reauthenticate = reauthenticate

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        """A token from ``az account get-access-token``, signing the Azure CLI in again first when
        its sign-in has lapsed and ``reauthenticate`` can."""
        try:
            data = self._fetch(resource, tenant_id)
        except AzCliError as exc:
            reason = lapse_reason(str(exc))
            if reason is None:
                raise
            if self._reauthenticate is None or not self._reauthenticate(tenant_id, reason):
                raise ReauthRequired(
                    f"the Azure CLI's sign-in to tenant {tenant_id} has lapsed: {reason}",
                    hint=(
                        f"sign in again with {brand.command('az use <profile>')} "
                        f"or 'az login --tenant {tenant_id}'"
                    ),
                    tenant_id=tenant_id,
                    reason=reason,
                ) from None
            data = self._fetch(resource, tenant_id)
        return self._token(data, resource, tenant_id)

    def _fetch(self, resource: str, tenant_id: str) -> Any:
        return self._runner.run_json(
            "account", "get-access-token", "--resource", resource, "--tenant", tenant_id
        )

    def _token(self, data: Any, resource: str, tenant_id: str) -> AccessToken:
        if not isinstance(data, dict) or not isinstance(data.get("accessToken"), str):
            raise AzCliError("az account get-access-token returned no accessToken")
        return AccessToken(
            token=data["accessToken"],
            expires_on=_expiry(data),
            tenant_id=str(data.get("tenant") or tenant_id).lower(),
            resource=resource,
        )


def _expiry(data: Mapping[str, Any]) -> datetime:
    # 'expires_on' (POSIX seconds) exists from az 2.54; older releases only have
    # 'expiresOn', a local time with no offset.
    epoch = data.get("expires_on")
    if isinstance(epoch, str) and epoch.isdigit():
        epoch = int(epoch)
    if isinstance(epoch, int | float) and not isinstance(epoch, bool):
        return datetime.fromtimestamp(epoch, UTC)
    text = data.get("expiresOn")
    if isinstance(text, str):
        try:
            return datetime.fromisoformat(text).astimezone(UTC)
        except ValueError:
            pass
    raise AzCliError("az account get-access-token returned no usable expiry")
