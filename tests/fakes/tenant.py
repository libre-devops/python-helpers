"""A fake Microsoft tenant for the CLI tests, and helpers to run a command against it.

``Tenant`` answers every API the commands call; ``invoke`` runs a command against it
with a fake Azure CLI, so nothing reaches the network.
"""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

from typer.testing import CliRunner

from fakes.azcli import account_json, az_runner
from fakes.http import fake_session
from fakes.ids import CLIENT_ID, OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core.token_store import MemoryStore

WORKSPACE = "abababab-abab-abab-abab-abababababab"

USER_ID = "88888888-8888-8888-8888-888888888888"

NOW = datetime.now(UTC)

CONFIG = f"""
[microsoft]
default_profile = "tenant"

[microsoft.profiles.tenant]
tenant_id = "{TENANT}"
workspace_id = "{WORKSPACE}"

[microsoft.profiles.app]
tenant_id = "{TENANT}"
auth = "client-secret"
client_id = "{CLIENT_ID}"
"""

runner = CliRunner()


def iso(days: float) -> str:
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def az_responder(args: list[str]) -> tuple[int, str, str]:
    if args[:2] == ["account", "list"]:
        return (0, json.dumps([account_json(SUBSCRIPTION, TENANT, default=True)]), "")
    if args[:2] == ["account", "get-access-token"]:
        resource = args[args.index("--resource") + 1]
        token = make_jwt(graph_claims(aud=resource.rstrip("/")))
        expires = int(NOW.timestamp()) + 3600
        return (0, json.dumps({"accessToken": token, "expires_on": expires}), "")
    raise AssertionError(f"unexpected az call: {args}")


class Tenant:
    """Replies for every API the commands call, keyed on host and path."""

    def __init__(self) -> None:
        self.devices = {"web01"}
        self.machines = {"web01"}
        self.requests: list = []
        # Called before every request, so a test can change the tenant over time.
        self.before = lambda: None

    def __call__(self, request):
        self.before()
        self.requests.append(request)
        parts = urlsplit(request.url)
        host, path = parts.netloc, parts.path
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        name = query.get("$filter", "").split("'")[1] if "'" in query.get("$filter", "") else ""
        if host == "login.microsoftonline.com":
            return (
                200,
                {"access_token": make_jwt(graph_claims(appid=CLIENT_ID)), "expires_in": 3600},
            )
        if host == "graph.microsoft.com":
            return self.graph(path, name)
        if host == "api.securitycenter.microsoft.com":
            return self.defender(path, name)
        if host == "management.azure.com":
            return self.arm(request, path)
        if host == "api.loganalytics.io":
            table = {"columns": [{"name": "Computer"}], "rows": [["web01"]]}
            return (200, {"tables": [table]})
        if host == "kv-app.vault.azure.net":
            if path == "/secrets":
                item = {
                    "id": "https://kv-app.vault.azure.net/secrets/db",
                    "attributes": {"exp": int((NOW + timedelta(days=5)).timestamp())},
                }
                return (200, {"value": [item]})
            return (200, {"value": []})
        raise AssertionError(f"unexpected request {unquote(request.url)}")

    def graph(self, path: str, name: str):
        if path == "/v1.0/devices":
            found = (
                [{"id": USER_ID, "displayName": name, "accountEnabled": True}]
                if name in self.devices
                else []
            )
            return (200, {"value": found})
        if path.endswith("/transitiveMemberOf/microsoft.graph.group"):
            return (200, {"value": []})
        if path == "/v1.0/users/ana@example.com":
            return (
                200,
                {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"},
            )
        if path == "/v1.0/identity/conditionalAccess/policies":
            return (200, {"value": []})
        if path == "/v1.0/applications":
            app = {
                "id": "o1",
                "appId": "a1",
                "displayName": "billing-api",
                "passwordCredentials": [
                    {"keyId": "k1", "displayName": "ci", "endDateTime": iso(3)}
                ],
                "keyCredentials": [],
            }
            return (200, {"value": [app]})
        raise AssertionError(f"unexpected Graph path {path}")

    def defender(self, path: str, name: str):
        if path == "/api/machines":
            found = (
                [
                    {
                        "id": "a" * 40,
                        "computerDnsName": name,
                        "onboardingStatus": "Onboarded",
                        "healthStatus": "Active",
                        "lastSeen": iso(0),
                    }
                ]
                if name in self.machines
                else []
            )
            return (200, {"value": found})
        if path == "/api/advancedqueries/run":
            return (200, {"Schema": [{"Name": "DeviceName"}], "Results": [{"DeviceName": "web01"}]})
        raise AssertionError(f"unexpected Defender path {path}")

    def arm(self, request, path: str):
        if path == "/providers/Microsoft.ResourceGraph/resources":
            return (200, {"data": [{"name": "kv-app", "type": "microsoft.keyvault/vaults"}]})
        if path.endswith("/roleAssignments"):
            item = {
                "id": "ra1",
                "properties": {
                    "scope": f"/subscriptions/{SUBSCRIPTION}",
                    "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/r",
                    "principalId": USER_ID,
                    "principalType": "User",
                },
            }
            return (200, {"value": [item]})
        if "roleDefinitions" in path:
            return (200, {"properties": {"roleName": "Reader"}})
        raise AssertionError(f"unexpected ARM path {path}")


def invoke(config_file, tenant, args, *, environ=None, clock=None, stdin=None):
    obj = Runtime(
        config_path=config_file,
        token_store=MemoryStore(),
        has_browser=lambda: False,
        open_browser=lambda url: None,
        az_runner=az_runner(az_responder)[0],
        session=fake_session(tenant)[0],
        environ=environ or {},
    )
    if clock is not None:
        obj.clock, obj.sleep = clock, clock.sleep
    return runner.invoke(app, args, obj=obj, input=stdin)


PROFILES_CONFIG = f"""
[microsoft]
default_profile = "prod-tenant"

[microsoft.profiles.prod]
tenant_id = "{TENANT}"
subscription_id = "{SUBSCRIPTION}"

[microsoft.profiles.prod-tenant]
tenant_id = "{TENANT}"

[microsoft.profiles.test-tenant]
tenant_id = "{OTHER_TENANT}"
"""


def runtime(config_path, handler=None, environ=None) -> Runtime:
    session = fake_session(handler)[0] if handler else None
    return Runtime(
        config_path=config_path,
        token_store=MemoryStore(),
        has_browser=lambda: False,
        open_browser=lambda url: None,
        az_runner=az_runner(az_responder)[0],
        session=session,
        environ=environ or {},
    )


def run(config_path, handler, args, *, stdin=None, environ=None, az=None, confirm=None):
    """Run a command with ``handler`` answering its API calls (see fakes.http.routes).

    ``az`` answers Azure CLI calls; ``confirm``, when given, makes the run look like a
    terminal and answers each yes-or-no question the command asks.
    """
    obj = runtime(config_path, handler, environ)
    if az is not None:
        obj.az_runner = az_runner(az)[0]
    if confirm is not None:
        obj.interactive = lambda: True
        obj.confirm = confirm
    return runner.invoke(app, args, obj=obj, input=stdin)
