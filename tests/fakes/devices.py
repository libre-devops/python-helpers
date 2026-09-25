"""A fake tenant for the device checks: Entra devices, Defender machines, groups."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.intune import IntuneClient
from libre_devops_helpers.microsoft.xdr import XdrClient

GROUP_ID = "55555555-5555-5555-5555-555555555555"
# A second group, for devices expected in two ("Pilot" and "Patched").
PATCHED_ID = "66666666-6666-6666-6666-666666666666"

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def object_id(name: str) -> str:
    return f"{abs(hash(name)) % 10**8:08d}-0000-4000-8000-000000000000"


def device_id(name: str) -> str:
    return f"{abs(hash(name + 'd')) % 10**8:08d}-1111-4111-8111-111111111111"


class FakeTenant:
    """Entra, Defender and Intune for a handful of devices, changeable between passes."""

    def __init__(self) -> None:
        self.entra: dict[str, list[dict]] = {}
        self.machines: dict[str, list[dict]] = {}
        self.managed: dict[str, list[dict]] = {}
        self.group_members: list[str] = []
        self.patched_members: list[str] = []
        self.fail: dict[str, tuple[int, dict]] = {}
        self.calls: list[str] = []

    def add(
        self,
        name: str,
        *,
        onboarded: bool = True,
        tags=(),
        device_group="UnassignedGroup",
        last_seen="2026-09-24T11:00:00Z",
    ):
        self.entra.setdefault(name, []).append(
            {
                "id": object_id(name),
                "displayName": name,
                "deviceId": device_id(name),
                "accountEnabled": True,
            }
        )
        self.machines.setdefault(name, []).append(
            {
                "id": (name * 40)[:40].encode().hex()[:40],
                "computerDnsName": name,
                "onboardingStatus": "Onboarded" if onboarded else "CanBeOnboarded",
                "healthStatus": "Active",
                "lastSeen": last_seen,
                "machineTags": list(tags),
                "rbacGroupName": device_group,
                "aadDeviceId": device_id(name),
            }
        )

    def enrol(self, name: str, *, compliance: str = "compliant", entra_id: str | None = None):
        """Add an Intune record for ``name``, linked to its Entra device unless told not."""
        self.managed.setdefault(name, []).append(
            {
                "id": f"m-{name}-{len(self.managed.get(name, []))}",
                "deviceName": name,
                "complianceState": compliance,
                "managementAgent": "mdm",
                "lastSyncDateTime": "2026-09-24T10:00:00Z",
                "azureADDeviceId": entra_id or device_id(name),
            }
        )

    def handler(self, request):
        url = unquote(request.url)
        parts = urlsplit(request.url)
        query = parse_qs(parts.query)
        self.calls.append(url)
        for fragment, reply in self.fail.items():
            if fragment in url:
                return reply
        if parts.path == "/v1.0/devices":
            name = query["$filter"][0].split("'")[1]
            return (200, {"value": self.entra.get(name, [])})
        if parts.path == "/v1.0/groups":
            if "'Patched'" in query.get("$filter", [""])[0]:
                return (200, {"value": [{"id": PATCHED_ID, "displayName": "Patched"}]})
            return (200, {"value": [{"id": GROUP_ID, "displayName": "Pilot"}]})
        if parts.path == f"/v1.0/groups/{GROUP_ID}":
            return (200, {"id": GROUP_ID, "displayName": "Pilot"})
        if parts.path.endswith("/transitiveMembers/microsoft.graph.device"):
            members = self.patched_members if PATCHED_ID in parts.path else self.group_members
            return (200, {"value": [{"id": object_id(name)} for name in members]})
        if parts.path.endswith("/transitiveMemberOf/microsoft.graph.group"):
            return (200, {"value": [{"id": GROUP_ID, "displayName": "Pilot"}]})
        if parts.path == "/v1.0/deviceManagement/managedDevices":
            name = query["$filter"][0].split("'")[1]
            return (200, {"value": self.managed.get(name, [])})
        if parts.path == "/api/machines":
            name = query["$filter"][0].split("'")[1]
            return (200, {"value": self.machines.get(name, [])})
        raise AssertionError(f"unexpected request {url}")

    def defender_calls(self, name: str) -> int:
        return sum(1 for url in self.calls if "/api/machines" in url and f"'{name}'" in url)


def clients(tenant: FakeTenant, tokens=None):
    """Entra and Defender clients over ``tenant``, with ``tokens`` or static ones."""
    session, _ = fake_session(tenant.handler)
    tokens = tokens or StaticTokens()
    return (
        EntraClient.create(tokens, TENANT, session=session),
        XdrClient.create(tokens, TENANT, session=session),
    )


def intune_client(tenant: FakeTenant) -> IntuneClient:
    session, _ = fake_session(tenant.handler)
    return IntuneClient.create(StaticTokens(), TENANT, session=session)
