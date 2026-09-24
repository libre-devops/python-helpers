from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.microsoft.intune import IntuneClient

ENTRA_DEVICE_ID = "12121212-1212-1212-1212-121212121212"


def managed(name: str, synced: str, compliance: str = "compliant", **extra) -> dict:
    return {
        "id": f"m-{synced}",
        "deviceName": name,
        "complianceState": compliance,
        "lastSyncDateTime": synced,
        "azureADDeviceId": ENTRA_DEVICE_ID,
        **extra,
    }


def intune(handler):
    session, adapter = fake_session(handler)
    return IntuneClient.create(StaticTokens(), TENANT, session=session), adapter


def test_find_devices_falls_back_to_short_name_newest_sync_first():
    rows = [managed("laptop", "2026-09-01T00:00:00Z"), managed("laptop", "2026-09-20T00:00:00Z")]

    def handler(request):
        return (200, {"value": rows if "'laptop'" in unquote(request.url) else []})

    client, adapter = intune(handler)
    found = client.find_devices("laptop.corp.example.com")
    assert [d.last_sync.day for d in found] == [20, 1]
    assert found[0].compliant
    assert len(adapter.requests) == 2
    assert urlsplit(adapter.requests[0].url).path == "/v1.0/deviceManagement/managedDevices"


def test_an_unlinked_device_has_no_entra_id():
    row = managed(
        "kiosk", "2026-09-20T00:00:00Z", azureADDeviceId="00000000-0000-0000-0000-000000000000"
    )
    client, _ = intune(lambda request: (200, {"value": [row]}))
    assert client.find_devices("kiosk")[0].azure_ad_device_id == ""


def test_for_entra_device_filters_on_the_device_id():
    client, adapter = intune(lambda request: (200, {"value": []}))
    client.for_entra_device(ENTRA_DEVICE_ID)
    query = parse_qs(urlsplit(adapter.requests[0].url).query)
    assert query["$filter"] == [f"azureADDeviceId eq '{ENTRA_DEVICE_ID}'"]
    with pytest.raises(LdoError, match="not an Entra device id"):
        client.for_entra_device("laptop")
