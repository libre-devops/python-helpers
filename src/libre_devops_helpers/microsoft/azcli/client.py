"""Azure CLI accounts and sign-in.

The subprocess handling lives in ``core.process``; tokens come from
``core.auth.AzureCliCredential``. This module is only about which accounts the CLI
knows and which one is active.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from libre_devops_helpers.microsoft.process import AzCliError, AzureCliRunner, signed_out


@dataclass(frozen=True)
class Account:
    """One entry from ``az account list``: a subscription, or a tenant-level sign-in."""

    id: str
    name: str
    tenant_id: str
    state: str
    is_default: bool
    user: str

    @property
    def tenant_level(self) -> bool:
        """True for the entry ``az login --allow-no-subscriptions`` records for a tenant."""
        return self.id == self.tenant_id

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Account:
        user = data.get("user")
        return cls(
            id=str(data.get("id", "")).lower(),
            name=str(data.get("name", "")),
            tenant_id=str(data.get("tenantId", "")).lower(),
            state=str(data.get("state", "")),
            is_default=bool(data.get("isDefault", False)),
            user=str(user.get("name", "")) if isinstance(user, Mapping) else "",
        )


class AzCli:
    """The Azure CLI's accounts: list them, read the active one, switch, sign in."""

    def __init__(self, runner: AzureCliRunner | None = None) -> None:
        self.runner = runner or AzureCliRunner()

    def current_account(self) -> Account | None:
        """The active account, or None when the CLI is not signed in."""
        try:
            data = self.runner.run_json("account", "show")
        except AzCliError as exc:
            if signed_out(str(exc)):
                return None
            raise
        return Account.from_json(data) if isinstance(data, dict) else None

    def accounts(self) -> list[Account]:
        """Every account the CLI knows, including disabled subscriptions."""
        data = self.runner.run_json("account", "list", "--all")
        return [Account.from_json(item) for item in data or [] if isinstance(item, dict)]

    def set_account(self, subscription: str) -> None:
        """Make ``subscription`` (an id or tenant-level entry) the active account."""
        self.runner.run("account", "set", "--subscription", subscription, "--only-show-errors")

    def login(
        self, tenant_id: str, *, device_code: bool = False, allow_no_subscriptions: bool = False
    ) -> None:
        """Sign in to ``tenant_id`` interactively (browser, or device code)."""
        args = ["login", "--tenant", tenant_id, "--output", "none"]
        if device_code:
            args.append("--use-device-code")
        if allow_no_subscriptions:
            args.append("--allow-no-subscriptions")
        # The account is chosen afterwards by 'az account set'; skip the CLI's own picker.
        self.runner.run(*args, interactive=True, env={"AZURE_CORE_LOGIN_EXPERIENCE_V2": "off"})
