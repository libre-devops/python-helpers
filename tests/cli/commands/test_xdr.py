import json
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

from fakes.http import json_body, routes
from fakes.tenant import invoke, run, runner, runtime
from libre_devops_helpers.cli import app

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
        **extra,
    }


def by_name(request):
    """Machines by computerDnsName: web01 exists, anything else does not."""
    return (200, {"value": [machine()] if "'web01'" in unquote(request.url) else []})


def test_hunt_with_endpoint_reads_the_query_from_stdin(config_file, tenant):
    args = ["xdr", "hunt", "--endpoint", "-o", "json"]
    result = invoke(config_file, tenant, args, stdin="DeviceInfo | take 1")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"DeviceName": "web01"}]
    hunt = next(r for r in tenant.requests if r.url.endswith("/api/advancedqueries/run"))
    assert json_body(hunt) == {"Query": "DeviceInfo | take 1"}


def test_check_devices_splits_names_and_exits_3_when_one_is_missing(profiles_config):
    record = {
        "id": "a" * 40,
        "computerDnsName": "web01",
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": "2026-09-20T00:00:00Z",
    }

    def handler(request):
        found = "'web01'" in unquote(request.url)
        return (200, {"value": [record] if found else []})

    result = runner.invoke(
        app, ["xdr", "machines", "web01,ghost", "-o", "json"], obj=runtime(profiles_config, handler)
    )
    assert result.exit_code == 3, result.output
    lookups = json.loads(result.stdout)
    assert [(item["query"], item["found"]) for item in lookups] == [
        ("web01", True),
        ("ghost", False),
    ]


def test_machines_table_shows_health_tags_and_older_records(config_file):
    older = machine(last_seen=ago(40), id="b" * 40, healthStatus="Inactive")
    handler = routes({MACHINES: (200, {"value": [machine(), older]})})
    result = run(config_file, handler, ["xdr", "machines", "web01"])
    assert result.exit_code == 0, result.output
    assert "linux-servers" in result.stdout
    assert "older record" not in result.stdout
    everything = run(config_file, handler, ["xdr", "machines", "web01", "--all-records"])
    assert "older record" in everything.stdout
    assert "Inactive" in everything.stdout


def test_stale_lists_silent_machines_and_exits_3(config_file):
    handler = routes({MACHINES: (200, {"value": [machine("old01", ago(45))]})})
    result = run(config_file, handler, ["xdr", "stale", "--older-than", "30d"])
    assert result.exit_code == 3, result.output
    assert "old01" in result.stdout
    assert "1 machine(s) not seen for 30d" in result.stderr
    quiet = run(config_file, routes({MACHINES: (200, {"value": []})}), ["xdr", "stale"])
    assert quiet.exit_code == 0


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


def test_hunt_goes_through_graph_by_default(config_file):
    reply = {"schema": [{"name": "Subject"}], "results": [{"Subject": "Invoice"}]}
    seen = []

    def hunting(request):
        seen.append(json_body(request))
        return (200, reply)

    handler = routes({"/v1.0/security/runHuntingQuery": hunting})
    args = ["xdr", "hunt", "EmailEvents | take 1", "--timespan", "7d", "-o", "json"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"Subject": "Invoice"}]
    assert seen == [{"Query": "EmailEvents | take 1", "Timespan": "P7D"}]


def test_a_timespan_needs_graph(config_file):
    args = ["xdr", "hunt", "DeviceInfo", "--endpoint", "--timespan", "7d"]
    result = run(config_file, routes({}), args)
    assert result.exit_code == 2
    assert "--timespan is not available with --endpoint" in result.output
