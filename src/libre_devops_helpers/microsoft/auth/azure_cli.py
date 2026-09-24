"""Tokens from the Azure CLI's own sign-in (``az account get-access-token``)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from libre_devops_helpers.core.auth import AccessToken
from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner


class AzureCliCredential:
    """A token provider backed by the Azure CLI session of the person running the tool.

    ``--tenant`` is passed explicitly, so this works for any signed-in tenant and does
    not depend on, or change, the CLI's active account.
    """

    def __init__(self, runner: AzureCliRunner | None = None) -> None:
        self._runner = runner or AzureCliRunner()

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        data = self._runner.run_json(
            "account", "get-access-token", "--resource", resource, "--tenant", tenant_id
        )
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
