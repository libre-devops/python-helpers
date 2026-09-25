from fakes.http import routes
from fakes.tenant import run
from fakes.xdr import MACHINE_ID, MACHINES, ago, by_name


def test_alerts_for_a_device_use_its_machine_and_filter_by_severity(config_file):
    alert = {
        "id": "da1",
        "title": "Suspicious process",
        "severity": "High",
        "status": "New",
        "alertCreationTime": ago(1),
        "computerDnsName": "web01",
        "category": "Execution",
        "detectionSource": "EDR",
    }
    handler = routes(
        {MACHINES: by_name, f"{MACHINES}/{MACHINE_ID}/alerts": (200, {"value": [alert]})}
    )
    args = ["xdr", "alerts", "--device", "web01", "--severity", "medium", "--since", "2d"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    assert "Suspicious process" in result.stdout
    assert "1 alert(s) in the last 2d" in result.stderr


def test_alerts_for_an_unknown_device_is_not_found(config_file):
    result = run(config_file, routes({MACHINES: by_name}), ["xdr", "alerts", "-d", "ghost"])
    assert result.exit_code == 1
    assert "no Defender record for 'ghost'" in str(result.exception)


def test_alerts_reject_an_unknown_severity(config_file):
    result = run(config_file, routes({}), ["xdr", "alerts", "--severity", "urgent"])
    assert "unknown severity" in str(result.exception)


def test_vulns_keep_only_those_at_or_above_the_floor(config_file):
    rows = [
        {"id": "CVE-1", "name": "minor", "severity": "Low", "cvssV3": 3.1},
        {
            "id": "CVE-2",
            "name": "major",
            "severity": "Critical",
            "cvssV3": 9.8,
            "exploitVerified": True,
        },
        {"id": "CVE-3", "name": "odd", "severity": "Unknown"},
    ]
    handler = routes(
        {MACHINES: by_name, f"{MACHINES}/{MACHINE_ID}/vulnerabilities": (200, {"value": rows})}
    )
    result = run(config_file, handler, ["xdr", "vulns", "web01", "--severity", "high"])
    assert result.exit_code == 0, result.output
    assert "CVE-2" in result.stdout
    assert "verified" in result.stdout
    assert "CVE-1" not in result.stdout
    assert "CVE-3" not in result.stdout
    assert "1 vulnerability on web01" in result.stderr
    missing = run(config_file, handler, ["xdr", "vulns", "ghost"])
    assert "no Defender record for 'ghost'" in str(missing.exception)


def test_vulns_with_a_not_known_publish_date_show_a_dash(config_file):
    rows = [
        {
            "id": "CVE-9",
            "name": "undated",
            "severity": "High",
            "publishedOn": "0001-01-01T00:00:00Z",
        }
    ]
    handler = routes(
        {MACHINES: by_name, f"{MACHINES}/{MACHINE_ID}/vulnerabilities": (200, {"value": rows})}
    )
    result = run(config_file, handler, ["xdr", "vulns", "web01", "-o", "csv"])
    assert result.exit_code == 0, result.output
    row = dict(zip(*[line.split(",") for line in result.stdout.splitlines()[:2]], strict=True))
    assert row["PUBLISHED"] == "-"


def test_vulns_sort_and_unique_by_their_columns(config_file):
    rows = [
        {"id": "CVE-1", "name": "minor", "severity": "Low", "cvssV3": 3.1},
        {"id": "CVE-2", "name": "major", "severity": "Critical", "cvssV3": 9.1},
        {"id": "CVE-3", "name": "worse", "severity": "Critical", "cvssV3": 9.8},
        {"id": "CVE-4", "name": "middling", "severity": "Medium", "cvssV3": 5.5},
    ]
    handler = routes(
        {MACHINES: by_name, f"{MACHINES}/{MACHINE_ID}/vulnerabilities": (200, {"value": rows})}
    )
    args = ["xdr", "vulns", "web01", "-o", "csv", "--sort", "severity:desc", "--sort", "cvss:desc"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    assert [line.split(",")[0] for line in result.stdout.splitlines()[1:]] == [
        "CVE-3",
        "CVE-2",
        "CVE-4",
        "CVE-1",
    ]
    one_each = run(config_file, handler, [*args, "--unique", "severity"])
    assert [line.split(",")[0] for line in one_each.stdout.splitlines()[1:]] == [
        "CVE-3",
        "CVE-4",
        "CVE-1",
    ]
    unknown = run(config_file, handler, ["xdr", "vulns", "web01", "--sort", "owner"])
    assert "no 'owner' column" in str(unknown.exception)
    bad = run(config_file, handler, ["xdr", "vulns", "web01", "--sort", "cvss:up"])
    assert bad.exit_code == 2


def test_indicators_are_listed(config_file):
    row = {
        "id": "1",
        "indicatorValue": "203.0.113.7",
        "indicatorType": "IpAddress",
        "action": "Block",
        "title": "known bad",
    }
    handler = routes({"/api/indicators": (200, {"value": [row]})})
    result = run(config_file, handler, ["xdr", "indicators", "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert "IpAddress,203.0.113.7,Block" in result.stdout
