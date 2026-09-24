import json
from datetime import UTC, datetime, timedelta

from fakes.http import routes
from fakes.incidents import alert, incident, query
from fakes.tenant import run

PATH = "/v1.0/security/incidents"


def iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now().astimezone() + delta).isoformat()


def serving(records, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(query(request))
        return (200, {"value": records})

    return routes({PATH: handler})


def test_top_is_todays_open_incidents_most_severe_first(config_file):
    seen: list[dict] = []
    records = [
        incident(1, severity="low", created=iso(-timedelta(minutes=5))),
        incident(2, severity="high", created=iso(-timedelta(minutes=30))),
        incident(3, severity="medium", created=iso(-timedelta(minutes=10))),
    ]
    result = run(config_file, serving(records, seen), ["xdr", "incidents", "top", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert [item["id"] for item in json.loads(result.stdout)] == ["2", "3", "1"]
    sent = seen[0]["$filter"]
    assert "createdDateTime ge " in sent
    assert "createdDateTime lt " in sent
    assert "status eq 'active' or status eq 'inProgress' or status eq 'awaitingAction'" in sent
    assert "3 of 3 incident(s) created today" in result.stderr


def test_top_limits_to_ten_by_default_and_n_changes_it(config_file):
    records = [incident(n, created=iso(-timedelta(minutes=n))) for n in range(1, 13)]
    result = run(config_file, serving(records), ["xdr", "incidents", "top", "-o", "csv"])
    assert len(result.stdout.splitlines()) == 11  # the header and ten
    three = run(config_file, serving(records), ["xdr", "incidents", "top", "-n", "3", "-o", "csv"])
    assert len(three.stdout.splitlines()) == 4
    assert "3 of 12 incident(s)" in three.stderr


def test_latest_is_the_newest_of_any_status_from_the_last_30_days(config_file):
    seen: list[dict] = []
    records = [
        incident(1, status="resolved", created="2026-09-01T09:00:00Z"),
        incident(2, created="2026-09-20T09:00:00Z"),
    ]
    result = run(config_file, serving(records, seen), ["xdr", "incidents", "latest", "-o", "json"])
    assert [item["id"] for item in json.loads(result.stdout)] == ["2", "1"]
    assert "status" not in seen[0]["$filter"]
    assert "lt" not in seen[0]["$filter"]
    assert "the last 30d" in result.stderr


def test_list_between_days_takes_both_days_whole(config_file):
    seen: list[dict] = []
    args = ["xdr", "incidents", "list", "--from", "2026-09-01", "--to", "2026-09-03"]
    result = run(config_file, serving([incident(1)], seen), args)
    assert result.exit_code == 0, result.output
    # Local midnight at the start of the 1st, to local midnight after the 3rd, in UTC.
    first = datetime(2026, 9, 1).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    after = datetime(2026, 9, 4).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert seen[0]["$filter"] == f"createdDateTime ge {first} and createdDateTime lt {after}"
    assert "Incident 1" in result.stdout
    assert "created 2026-09-01 to 2026-09-03" in result.stderr


def test_list_can_window_on_updates_and_filter_status_and_severity(config_file):
    seen: list[dict] = []
    args = [
        "xdr",
        "incidents",
        "list",
        "--since",
        "6h",
        "--updated",
        "--status",
        "resolved",
        "--severity",
        "medium",
    ]
    run(config_file, serving([], seen), args)
    sent = seen[0]["$filter"]
    assert sent.startswith("lastUpdateDateTime ge ")
    assert "status eq 'resolved'" in sent
    assert "(severity eq 'high' or severity eq 'medium')" in sent


def test_the_source_filter_finds_sentinel_incidents(config_file):
    records = [
        incident(1, sources=("microsoftDefenderForEndpoint",)),
        incident(2, sources=("microsoftSentinel",)),
    ]
    args = ["xdr", "incidents", "latest", "--source", "sentinel", "-o", "csv"]
    result = run(config_file, serving(records), args)
    rows = result.stdout.splitlines()
    assert len(rows) == 2
    assert "Sentinel" in rows[1]


def test_bad_statuses_sources_and_windows_are_usage_errors(config_file):
    for args in (
        ["--status", "closed"],
        ["--source", "splunk"],
    ):
        result = run(config_file, serving([]), ["xdr", "incidents", "list", *args])
        assert result.exit_code == 2, result.output
    both = run(config_file, serving([]), ["xdr", "incidents", "list", "--today", "--since", "2h"])
    assert "choose one time window" in str(both.exception)


def test_summary_counts_by_severity_status_and_source(config_file):
    records = [
        incident(1, severity="high", sources=("microsoftSentinel",)),
        incident(2, severity="high", status="inProgress"),
        incident(3, severity="low", status="resolved"),
    ]
    result = run(config_file, serving(records), ["xdr", "incidents", "summary"])
    assert result.exit_code == 0, result.output
    assert "3 incident(s) today" in result.stdout
    assert "in progress" in result.stdout
    assert "Sentinel" in result.stdout
    record = json.loads(
        run(config_file, serving(records), ["xdr", "incidents", "summary", "-o", "json"]).stdout
    )
    assert record["by_severity"] == {"high": 2, "low": 1}
    assert record["by_source"] == {"Endpoint": 2, "Sentinel": 1}


def test_show_one_incident_with_its_alerts_devices_and_link(config_file):
    record = incident(
        42,
        assignedTo="ana@example.com",
        alerts=[
            alert(
                evidence=[
                    {
                        "@odata.type": "#microsoft.graph.security.deviceEvidence",
                        "deviceDnsName": "web01",
                    }
                ]
            ),
            alert("microsoftSentinel", severity="medium"),
        ],
    )
    handler = routes({f"{PATH}/42": (200, record)})
    result = run(config_file, handler, ["xdr", "incidents", "show", "42"])
    assert result.exit_code == 0, result.output
    assert "Incident 42: Incident 42" in result.stdout
    assert "web01" in result.stdout
    assert "Endpoint, Sentinel" in result.stdout
    assert "https://security.microsoft.com/incidents/42" in result.stdout
    as_csv = run(config_file, handler, ["xdr", "incidents", "show", "42", "-o", "csv"])
    assert len(as_csv.stdout.splitlines()) == 3


def test_a_missing_scope_explains_which_profile_to_use(config_file):
    denied = routes({PATH: (403, {"error": {"code": "Forbidden", "message": "no"}})})
    result = run(config_file, denied, ["xdr", "incidents", "top"])
    assert "SecurityIncident.Read.All" in (result.exception.hint or "")
