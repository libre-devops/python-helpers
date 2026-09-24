"""Azure CLI replies: accounts and a runner that answers az commands."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fakes.process import FakeRunner
from fakes.tokens import graph_claims, make_jwt


def account_json(
    subscription: str, tenant: str, *, name: str = "sub", default: bool = False
) -> dict[str, Any]:
    """One entry as ``az account list`` prints it."""
    return {
        "id": subscription,
        "name": name,
        "tenantId": tenant,
        "state": "Enabled",
        "isDefault": default,
        "user": {"name": "analyst@example.com", "type": "user"},
    }


def az_runner(respond: Callable[[list[str]], tuple[int, str, str]]):
    """An AzureCliRunner over a FakeRunner, returned with the fake for its call log."""
    from libre_devops_helpers.microsoft.process import AzureCliRunner

    fake = FakeRunner(respond)
    return AzureCliRunner("az", runner=fake), fake


class FakeAzState:
    """Enough of az's account state to exercise profile switching end to end.

    ``known`` is what ``az account list`` prints; ``active`` is the subscription id
    ``az account show`` reports, or None for a signed-out CLI. ``az login`` adds a
    tenant-level account for the tenant it signs in to. A tenant in ``lapsed`` refuses
    ``az account get-access-token`` the way the CLI does when its refresh token has run
    out, until ``az login`` signs in to it again.
    """

    LAPSED = (
        "ERROR: AADSTS70043: The refresh token has expired or is invalid due to sign-in "
        "frequency checks by conditional access. To re-authenticate, please run: az login"
    )

    def __init__(
        self, known: list[dict], active: str | None = None, lapsed: tuple[str, ...] = ()
    ) -> None:
        self.known = known
        self.active = active
        self.lapsed = {tenant.lower() for tenant in lapsed}
        self.logins: list[list[str]] = []
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(args)
        if args[:2] == ["account", "get-access-token"]:
            tenant = args[args.index("--tenant") + 1].lower()
            if tenant in self.lapsed:
                return (1, "", self.LAPSED)
            resource = args[args.index("--resource") + 1]
            token = make_jwt(graph_claims(aud=resource.rstrip("/"), tid=tenant))
            expires = int(datetime.now(UTC).timestamp()) + 3600
            return (0, json.dumps({"accessToken": token, "expires_on": expires}), "")
        if args[:2] == ["account", "list"]:
            return (0, json.dumps(self.known), "")
        if args[:2] == ["account", "set"]:
            self.active = args[3]
            return (0, "", "")
        if args[:2] == ["account", "show"]:
            if self.active is None:
                return (1, "", "ERROR: Please run 'az login' to setup account.")
            match = next(item for item in self.known if item["id"] == self.active)
            return (0, json.dumps({**match, "isDefault": True}), "")
        if args[0] == "login":
            self.logins.append(args)
            tenant = args[2]
            self.lapsed.discard(tenant.lower())
            if not any(item["tenantId"] == tenant for item in self.known):
                self.known.append(account_json(tenant, tenant, name="N/A(tenant level account)"))
            self.active = next(item["id"] for item in self.known if item["tenantId"] == tenant)
            return (0, "", "")
        raise AssertionError(f"unexpected az call: {args}")
