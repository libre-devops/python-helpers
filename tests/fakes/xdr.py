"""Defender for Endpoint machines as its API returns them, for the xdr command tests."""

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

MACHINE_ID = "a" * 40
MACHINES = "/api/machines"


def ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def machine(name: str = "web01", last_seen: str | None = None, **extra) -> dict:
    return {
        "id": MACHINE_ID,
        "computerDnsName": name,
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": last_seen or ago(0),
        "osPlatform": "Linux",
        "machineTags": ["linux-servers"],
        "rbacGroupName": "Linux servers",
        **extra,
    }


def by_name(request):
    """Machines by computerDnsName: web01 exists, anything else does not."""
    return (200, {"value": [machine()] if "'web01'" in unquote(request.url) else []})
