from datetime import UTC, datetime, timedelta, timezone

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.timewindow import Window
from libre_devops_helpers.microsoft.xdr import (
    outside_retention,
    parse_kinds,
    read_timeline,
    timeline_query,
)
from libre_devops_helpers.microsoft.xdr.timeline import DEVICE_KINDS, KINDS, MAX_EVENTS, RETENTION

BST = timezone(timedelta(hours=1))
MORNING = Window(datetime(2026, 9, 24, 9, tzinfo=BST), datetime(2026, 9, 24, 12, tzinfo=BST), "x")
TABLES = [
    "DeviceProcessEvents",
    "DeviceNetworkEvents",
    "DeviceFileEvents",
    "DeviceRegistryEvents",
    "DeviceLogonEvents",
    "DeviceImageLoadEvents",
    "DeviceEvents",
    "AlertEvidence",
]


def test_every_kind_of_event_is_asked_for_by_default_newest_first():
    query = timeline_query("web01.corp.example", MORNING)
    assert all(f"{table}\n" in query for table in TABLES)
    assert "join kind=leftouter (AlertInfo" in query
    assert query.endswith("| top 1000 by Timestamp desc")
    # Each kind is shaped to the same columns, so they union into one table.
    assert query.count("DeviceName, DeviceId, Id = ") == len(KINDS)


def test_only_the_kinds_asked_for_are_queried():
    query = timeline_query("web01", MORNING, ["logon,process"], limit=50)
    assert "union process_events, logon_events\n| top 50 by Timestamp desc" in query
    assert "DeviceNetworkEvents" not in query
    assert "AlertEvidence" not in query


def test_the_window_is_written_in_utc_and_an_open_end_is_left_out():
    query = timeline_query("web01", MORNING, ["process"])
    assert (
        "Timestamp >= datetime(2026-09-24T08:00:00Z) and Timestamp < datetime(2026-09-24T11:00:00Z)"
        in query
    )
    since = Window(datetime(2026, 9, 24, 8, tzinfo=UTC), None, "the last 1h")
    assert "| where Timestamp >= datetime(2026-09-24T08:00:00Z)\n" in timeline_query(
        "web01", since, ["process"]
    )
    assert "| where true\n" in timeline_query("web01", Window(None, None, "all"), ["process"])


def test_an_fqdn_matches_itself_or_its_host_name_alone():
    query = timeline_query("WEB01.corp.example.", MORNING, ["process"])
    assert query.startswith('let device = dynamic(["web01.corp.example", "web01"]);')
    assert "| where DeviceName in~ (device)\n" in query
    assert "startswith" not in query


def test_a_host_name_also_matches_an_fqdn_by_its_first_label_only():
    query = timeline_query("web01", MORNING, ["process"])
    assert query.startswith('let device = dynamic(["web01"]);')
    # web01.corp.example, yes; web010.corp.example, no: the dot is part of the prefix.
    assert '| where DeviceName in~ (device) or DeviceName startswith "web01."\n' in query


@pytest.mark.parametrize(
    "name",
    ['web01"', "web01 or 1==1", "web01;", "web01\n| take 1", "", "-web01", "web01/../x"],
    ids=["quote", "space", "semicolon", "line-break", "empty", "dash", "slash"],
)
def test_a_name_that_could_change_the_query_is_refused(name):
    with pytest.raises(InputError, match="not a device name"):
        timeline_query(name, MORNING)


@pytest.mark.parametrize("limit", [0, -1, MAX_EVENTS + 1])
def test_the_limit_is_within_what_a_query_returns(limit):
    with pytest.raises(InputError, match="the limit must be from 1 to 100,000"):
        timeline_query("web01", MORNING, limit=limit)


def test_kinds_are_named_by_comma_or_repeat_in_their_own_order():
    assert parse_kinds([]) == tuple(KINDS)
    assert parse_kinds(["Alert", "network,process"]) == ("process", "network", "alert")
    assert parse_kinds(["image-load image-load"]) == ("image-load",)
    with pytest.raises(InputError, match="unknown kind of event: usb, wmi") as caught:
        parse_kinds(["usb,wmi,process"])
    assert "image-load" in (caught.value.hint or "")


def test_the_endpoint_apis_kinds_are_the_device_tables_only():
    assert parse_kinds([], device_tables_only=True) == DEVICE_KINDS
    assert "alert" not in DEVICE_KINDS
    assert parse_kinds(["logon"], device_tables_only=True) == ("logon",)
    with pytest.raises(InputError, match="not in the Defender for Endpoint API's tables") as caught:
        parse_kinds(["alert,process"], device_tables_only=True)
    assert "--endpoint" in (caught.value.hint or "")


def row(when: str, kind: str = "process", device: str = "web01", device_id: str = "d1") -> dict:
    return {
        "Timestamp": when,
        "Type": kind,
        "ActionType": "ProcessCreated",
        "Detail": "bash -c id",
        "Account": "root",
        "Process": "sshd",
        "DeviceName": device,
        "DeviceId": device_id,
        "Id": "42",
    }


def test_rows_become_events_newest_first():
    result = QueryResult.from_records(
        [row("2026-09-24T08:00:00Z"), row("2026-09-24T09:30:00.1234567Z", kind="alert")]
    )
    found = read_timeline("web01", result, limit=10)
    first = found.events[0]
    assert (first.kind, first.time) == (
        "alert",
        datetime(2026, 9, 24, 9, 30, 0, 123456, tzinfo=UTC),
    )
    assert (first.action, first.detail, first.account, first.process, first.id) == (
        "ProcessCreated",
        "bash -c id",
        "root",
        "sshd",
        "42",
    )
    assert not found.truncated
    assert found.devices == ("web01 (d1)",)


def test_a_full_page_is_truncated_and_devices_sharing_a_name_are_told_apart():
    rows = [row("2026-09-24T08:00:00Z"), row("2026-09-24T07:00:00Z", device_id="d2")]
    found = read_timeline("web01", QueryResult.from_records(rows), limit=2)
    assert found.truncated
    assert found.devices == ("web01 (d1)", "web01 (d2)")
    empty = read_timeline("web01", QueryResult.from_records([]), limit=2)
    assert (empty.events, empty.truncated) == ((), False)


def test_a_window_older_than_advanced_hunting_keeps_is_flagged():
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    assert not outside_retention(Window(now - RETENTION + timedelta(hours=1), None, "x"), now)
    assert outside_retention(Window(now - RETENTION - timedelta(hours=1), None, "x"), now)
    assert outside_retention(Window(None, now, "x"), now)
