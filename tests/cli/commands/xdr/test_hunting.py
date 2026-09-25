import json

from fakes.http import json_body, routes
from fakes.tenant import invoke, run, usage_error


def test_hunt_with_endpoint_reads_the_query_from_stdin(config_file, tenant):
    args = ["xdr", "hunt", "--endpoint", "-o", "json"]
    result = invoke(config_file, tenant, args, stdin="DeviceInfo | take 1")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"DeviceName": "web01"}]
    hunt = next(r for r in tenant.requests if r.url.endswith("/api/advancedqueries/run"))
    assert json_body(hunt) == {"Query": "DeviceInfo | take 1"}


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
    assert "--timespan is not available with --endpoint" in usage_error(result)


def timeline_rows(*times: str, device_id: str = "d1") -> dict:
    """runHuntingQuery's reply for the timeline query: its columns, and a row per time."""
    columns = ["Timestamp", "Type", "ActionType", "Detail", "Account", "Process"]
    columns += ["DeviceName", "DeviceId", "Id"]
    rows = [
        {
            "Timestamp": when,
            "Type": "network",
            "ActionType": "ConnectionSuccess",
            "Detail": "203.0.113.7:443 example.com",
            "Account": "root",
            "Process": "curl",
            "DeviceName": "web01.corp.example",
            "DeviceId": device_id,
            "Id": "42",
        }
        for when in times
    ]
    return {"schema": [{"name": column} for column in columns], "results": rows}


def test_a_timeline_goes_through_graph_with_the_device_and_window_in_the_query(config_file):
    seen = []

    def hunting(request):
        seen.append(json_body(request)["Query"])
        return (200, timeline_rows("2026-09-24T08:00:05Z"))

    handler = routes({"/v1.0/security/runHuntingQuery": hunting})
    args = ["xdr", "timeline", "web01.corp.example", "--from", "2026-09-24T07:00Z", "-o", "csv"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    (query,) = seen
    assert 'dynamic(["web01.corp.example", "web01"])' in query
    assert "Timestamp >= datetime(2026-09-24T07:00:00Z)" in query
    header, line = result.stdout.splitlines()
    assert header == "TIME,TYPE,ACTION,ACCOUNT,PROCESS,DETAIL"
    assert line.endswith(",network,ConnectionSuccess,root,curl,203.0.113.7:443 example.com")
    assert "1 event(s) on web01.corp.example, from 2026-09-24 07:00Z" in result.stderr


def test_a_timeline_through_the_endpoint_writes_utc_in_json(config_file):
    def hunting(request):
        # The endpoint API's own casing: Schema and Name, Results.
        reply = timeline_rows("2026-09-24T08:00:05Z")
        schema = [{"Name": column["name"]} for column in reply["schema"]]
        return (200, {"Schema": schema, "Results": reply["results"]})

    handler = routes({"/api/advancedqueries/run": hunting})
    args = ["xdr", "timeline", "web01", "--since", "2h", "--type", "network", "--endpoint"]
    result = run(config_file, handler, [*args, "-o", "json"])
    assert result.exit_code == 0, result.output
    (event,) = json.loads(result.stdout)
    assert event["time"] == "2026-09-24T08:00:05+00:00"
    assert (event["type"], event["device_id"], event["id"]) == ("network", "d1", "42")


def test_a_timeline_warns_when_it_stops_short_or_two_devices_share_the_name(config_file):
    reply = timeline_rows("2026-09-24T08:00:05Z", "2026-09-24T07:00:05Z")
    reply["results"][1]["DeviceId"] = "d2"
    handler = routes({"/v1.0/security/runHuntingQuery": (200, reply)})
    result = run(config_file, handler, ["xdr", "timeline", "web01", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "stopped at the newest 2" in result.stderr
    assert "2 devices have that name: web01.corp.example (d1), web01.corp.example (d2)" in (
        result.stderr.replace("\n", " ")
    )


def test_a_timeline_past_thirty_days_says_advanced_hunting_keeps_no_more(config_file):
    handler = routes({"/v1.0/security/runHuntingQuery": (200, timeline_rows())})
    result = run(config_file, handler, ["xdr", "timeline", "web01", "--since", "45d"])
    assert result.exit_code == 0, result.output
    assert "0 event(s) on web01, the last 45d" in result.stderr
    assert "Advanced Hunting keeps 30 days of device events" in result.stderr


def test_a_timeline_query_can_be_shown_without_running_it(config_file):
    args = ["xdr", "timeline", "web01", "--type", "logon", "--show-query"]
    result = run(config_file, routes({}), args)  # any request would fail the test
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith('let device = dynamic(["web01"]);')
    assert "DeviceLogonEvents" in result.stdout


def test_a_timeline_refuses_a_name_or_kind_it_cannot_use(config_file):
    bad_name = run(config_file, routes({}), ["xdr", "timeline", 'web01" or true'])
    assert "not a device name that can go in a query" in str(bad_name.exception)
    bad_kind = run(config_file, routes({}), ["xdr", "timeline", "web01", "--type", "usb"])
    assert "unknown kind of event: usb" in str(bad_kind.exception)
    too_many = run(config_file, routes({}), ["xdr", "timeline", "web01", "--limit", "100001"])
    assert too_many.exit_code == 2
