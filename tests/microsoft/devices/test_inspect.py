from datetime import timedelta

from fakes.devices import NOW, FakeTenant, clients, intune_client, object_id
from libre_devops_helpers.microsoft.devices import (
    inspect_device,
)


def test_show_finds_nothing_wrong_with_a_healthy_device():
    tenant = FakeTenant()
    tenant.add("web01")
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, now=NOW)
    assert [(f.level, f.message) for f in view.findings] == [("ok", "nothing looks wrong")]
    assert view.groups[object_id("web01")][0].display_name == "Pilot"


def test_show_reports_duplicates_staleness_and_a_broken_entra_link():
    tenant = FakeTenant()
    tenant.add("web01", last_seen="2026-09-01T00:00:00Z")
    tenant.add("web01", last_seen="2026-08-01T00:00:00Z")
    tenant.machines["web01"][0]["aadDeviceId"] = "abcdabcd-0000-4000-8000-000000000000"
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, stale_after=timedelta(days=7), now=NOW)
    messages = [f.message for f in view.findings if f.level == "warn"]
    assert any("2 Entra objects share this name" in m for m in messages)
    assert any("2 Defender records" in m for m in messages)
    assert any(m.startswith("Defender last saw it") for m in messages)
    assert any("which is not one of the Entra objects" in m for m in messages)


def test_show_keeps_going_when_defender_cannot_be_read():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.fail["/api/machines"] = (
        403,
        {"error": {"code": "Unauthorized", "message": "Suspended account mode"}},
    )
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, now=NOW)
    assert view.defender is None
    assert any("Defender could not be read" in f.message for f in view.findings)
    assert view.entra


def test_show_reports_intune_duplicates_compliance_and_a_broken_link():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.enrol(
        "web01", compliance="noncompliant", entra_id="abcdabcd-0000-4000-8000-000000000000"
    )
    tenant.enrol("web01")
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, intune=intune_client(tenant), now=NOW)
    messages = [f.message for f in view.findings if f.level == "warn"]
    assert "2 Intune records; the newest sync is used" in messages
    assert "Intune compliance is noncompliant" in messages
    assert any(m.startswith("Intune links it to Entra device abcdabcd") for m in messages)


def test_show_notes_a_device_missing_from_intune_or_intune_unreadable():
    tenant = FakeTenant()
    tenant.add("web01")
    entra, _ = clients(tenant)
    view = inspect_device("web01", entra=entra, intune=intune_client(tenant), now=NOW)
    assert ("info", "not enrolled in Intune") in [(f.level, f.message) for f in view.findings]
    tenant.fail["managedDevices"] = (403, {"error": {"code": "Forbidden", "message": "no scope"}})
    view = inspect_device("web01", entra=entra, intune=intune_client(tenant), now=NOW)
    assert any("Intune could not be read" in f.message for f in view.findings)
    assert view.intune is None
