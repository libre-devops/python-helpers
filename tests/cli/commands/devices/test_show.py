import json

from fakes.tenant import invoke


def test_devices_show_passes_a_healthy_device_and_flags_a_missing_one(config_file, tenant):
    healthy = invoke(config_file, tenant, ["devices", "show", "web01"])
    assert healthy.exit_code == 0, healthy.output
    assert "nothing looks wrong" in healthy.stdout
    tenant.devices.add("web02")
    missing = invoke(config_file, tenant, ["devices", "show", "web02", "-o", "json"])
    assert missing.exit_code == 3, missing.output
    findings = json.loads(missing.stdout)["findings"]
    assert {"level": "warn", "message": "no Defender record"} in findings
