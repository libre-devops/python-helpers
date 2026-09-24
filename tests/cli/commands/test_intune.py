import json
from urllib.parse import unquote

from fakes.http import routes
from fakes.tenant import run

MANAGED = "/v1.0/deviceManagement/managedDevices"


def managed(name: str, synced: str, compliance: str = "compliant") -> dict:
    return {
        "id": f"m-{synced}",
        "deviceName": name,
        "complianceState": compliance,
        "operatingSystem": "Linux",
        "osVersion": "9.4",
        "lastSyncDateTime": synced,
        "userPrincipalName": "ana@example.com",
        "serialNumber": "SN1",
    }


def by_name(request):
    rows = [
        managed("web01", "2026-09-24T10:00:00Z"),
        managed("web01", "2026-08-01T10:00:00Z", "noncompliant"),
    ]
    return (200, {"value": rows if "'web01'" in unquote(request.url) else []})


def test_devices_shows_compliance_and_older_records(config_file):
    result = run(config_file, routes({MANAGED: by_name}), ["intune", "devices", "web01"])
    assert result.exit_code == 0, result.output
    assert "compliant" in result.stdout
    assert "older record" in result.stdout
    assert "1 of 1 enrolled in Intune" in result.stderr


def test_devices_not_enrolled_exit_3_and_json_keeps_every_record(config_file):
    args = ["intune", "devices", "web01,ghost", "-o", "json"]
    result = run(config_file, routes({MANAGED: by_name}), args)
    assert result.exit_code == 3, result.output
    records = json.loads(result.stdout)
    assert [(r["query"], len(r["devices"])) for r in records] == [("web01", 2), ("ghost", 0)]
    table = run(config_file, routes({MANAGED: by_name}), ["intune", "devices", "ghost"])
    assert "not enrolled" in table.stdout
