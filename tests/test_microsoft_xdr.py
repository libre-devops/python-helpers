from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fakes import TENANT, StaticTokens, fake_session, json_body
from libre_devops_helpers.core.errors import (
    ConfigError,
    LdoError,
    NotFoundError,
)
from libre_devops_helpers.microsoft.clouds import CHINA
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.xdr import XdrClient, parse_severity

MACHINE_ID = "a" * 40


def machine(name: str, last_seen: str, machine_id: str = MACHINE_ID) -> dict:
    return {
        "id": machine_id,
        "computerDnsName": name,
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": last_seen,
        "osPlatform": "Linux",
        "machineTags": ["linux-servers"],
    }


def xdr(handler, **options):
    session, adapter = fake_session(handler)
    tokens = StaticTokens()
    return XdrClient.create(tokens, TENANT, session=session, **options), adapter, tokens


def test_find_machine_falls_back_to_short_name_and_orders_newest_first():
    older = machine("web01", "2026-09-01T00:00:00Z", "b" * 40)
    newer = machine("web01", "2026-09-20T00:00:00.1234567Z")

    def handler(request):
        if "'web01'" in unquote(request.url):
            return (200, {"value": [older, newer]})
        return (200, {"value": []})

    client, adapter, _ = xdr(handler)
    lookup = client.find_machine("web01.corp.example.com")
    assert lookup.found
    assert lookup.matched_name == "web01"
    assert lookup.machine.id == MACHINE_ID
    assert [record.id for record in lookup.records] == [MACHINE_ID, "b" * 40]
    assert len(adapter.requests) == 2


def test_a_device_with_no_record_is_reported_not_found():
    client, _, _ = xdr(lambda request: (200, {"value": []}))
    lookup = client.find_machine("ghost.corp.example.com")
    assert not lookup.found
    assert lookup.machine is None
    assert lookup.matched_name is None


def test_filter_escapes_quotes_and_targets_computer_dns_name():
    client, adapter, _ = xdr(lambda request: (200, {"value": []}))
    client.machines_named("o'brien")
    request = adapter.requests[0]
    assert urlsplit(request.url).path == "/api/machines"
    assert parse_qs(urlsplit(request.url).query)["$filter"] == ["computerDnsName eq 'o''brien'"]


def test_regional_endpoint_still_uses_the_global_mde_token_resource():
    client, adapter, tokens = xdr(
        lambda request: (200, {"value": []}),
        api_url="https://api-eu.securitycenter.microsoft.com",
    )
    client.machines_named("web01")
    assert urlsplit(adapter.requests[0].url).netloc == "api-eu.securitycenter.microsoft.com"
    assert tokens.calls[0] == ("https://api.securitycenter.microsoft.com", TENANT)


def test_get_machine_validates_the_id_and_maps_404():
    client, adapter, _ = xdr(lambda request: (404, {"error": {"code": "ResourceNotFound"}}))
    with pytest.raises(LdoError, match="not an MDE machine id"):
        client.get_machine("../x")
    assert adapter.requests == []
    with pytest.raises(NotFoundError):
        client.get_machine(MACHINE_ID)


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def alert(alert_id: str, severity: str, status: str, created: str) -> dict:
    return {
        "id": alert_id,
        "title": f"alert {alert_id}",
        "severity": severity,
        "status": status,
        "alertCreationTime": created,
        "computerDnsName": "web01",
    }


def test_stale_machines_filter_on_the_server_and_sort_longest_silent_first():
    rows = [machine("b", "2026-08-20T00:00:00Z", "b" * 40), machine("a", "2026-07-01T00:00:00Z")]
    client, adapter, _ = xdr(lambda request: (200, {"value": rows}))
    found = client.stale_machines(timedelta(days=30), now=NOW)
    assert [m.computer_dns_name for m in found] == ["a", "b"]
    assert parse_qs(urlsplit(adapter.requests[0].url).query)["$filter"] == [
        "lastSeen lt 2026-08-25T12:00:00Z"
    ]


def test_alerts_filter_open_and_by_severity_newest_first():
    rows = [
        alert("1", "Low", "New", "2026-09-20T00:00:00Z"),
        alert("2", "High", "Resolved", "2026-09-21T00:00:00Z"),
        alert("3", "Medium", "InProgress", "2026-09-22T00:00:00Z"),
        alert("4", "UnSpecified", "New", "2026-09-23T00:00:00Z"),
    ]
    client, adapter, _ = xdr(lambda request: (200, {"value": rows}))
    since = datetime(2026, 9, 1, tzinfo=UTC)
    found = client.alerts(since=since, min_severity="medium")
    assert [a.id for a in found] == ["3"]
    query = parse_qs(urlsplit(adapter.requests[0].url).query)
    assert query["$filter"] == ["alertCreationTime ge 2026-09-01T00:00:00Z"]
    everything = client.alerts(include_resolved=True)
    assert [a.id for a in everything] == ["4", "3", "2", "1"]


def test_alerts_for_one_machine_use_its_endpoint():
    client, adapter, _ = xdr(lambda request: (200, {"value": []}))
    client.alerts(machine_id=MACHINE_ID)
    assert urlsplit(adapter.requests[0].url).path == f"/api/machines/{MACHINE_ID}/alerts"


def test_an_unknown_severity_from_a_person_is_rejected():
    with pytest.raises(LdoError, match="unknown severity"):
        parse_severity("urgent")


def test_vulnerabilities_are_most_severe_first():
    rows = [
        {"id": "CVE-1", "severity": "Medium", "cvssV3": 5.0},
        {"id": "CVE-2", "severity": "Critical", "cvssV3": 9.8, "exploitVerified": True},
        {"id": "CVE-3", "severity": "Critical", "cvssV3": 9.1},
    ]
    client, adapter, _ = xdr(lambda request: (200, {"value": rows}))
    found = client.vulnerabilities(MACHINE_ID)
    assert [v.id for v in found] == ["CVE-2", "CVE-3", "CVE-1"]
    assert found[0].exploit_verified
    path = f"/api/machines/{MACHINE_ID}/vulnerabilities"
    assert urlsplit(adapter.requests[0].url).path == path


def test_hunt_posts_the_query_and_keeps_the_schema_column_order():
    reply = {
        "Schema": [{"Name": "DeviceName", "Type": "String"}, {"Name": "Count", "Type": "Int64"}],
        "Results": [{"Count": 3, "DeviceName": "web01"}],
    }
    client, adapter, _ = xdr(lambda request: (200, reply))
    result = client.hunt("DeviceInfo | summarize Count=count() by DeviceName")
    assert result.columns == ("DeviceName", "Count")
    assert result.rows[0]["Count"] == 3
    request = adapter.requests[0]
    assert request.method == "POST"
    assert urlsplit(request.url).path == "/api/advancedqueries/run"
    assert json_body(request) == {"Query": "DeviceInfo | summarize Count=count() by DeviceName"}


def test_indicators_are_read():
    row = {"id": "1", "indicatorValue": "1.2.3.4", "indicatorType": "IpAddress", "action": "Block"}
    client, _, _ = xdr(lambda request: (200, {"value": [row]}))
    assert [(i.indicator_type, i.value) for i in client.indicators()] == [("IpAddress", "1.2.3.4")]


def test_a_cloud_without_defender_is_refused():
    with pytest.raises(ConfigError, match="not available"):
        XdrClient.for_profile(Profile("cn", TENANT, cloud=CHINA), StaticTokens())
