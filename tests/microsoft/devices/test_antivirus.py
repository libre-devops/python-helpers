import json
import re

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.microsoft.devices import av_query, av_statuses, version_key
from libre_devops_helpers.microsoft.devices.antivirus import mode_label


def row(name, signature="1.419.120.0", **fields):
    return {
        "DeviceId": f"id-{name}",
        "DeviceName": name,
        "OSPlatform": "Windows11",
        "Reported": "2026-09-24T08:00:00Z",
        "AvSignatureVersion": signature,
        "AvEngineVersion": "1.1.24080.9",
        "AvPlatformVersion": "4.18.24080.9",
        "AvMode": "0",
        "SignatureUpToDate": True,
        **fields,
    }


def wanted(query):
    return json.loads(re.search(r"dynamic\((\[.*?\])\)", query).group(1))


def test_the_query_looks_for_each_fqdn_and_short_name_once():
    query = av_query(["web01.corp.example.com", "WEB01", "db01"])
    assert wanted(query) == ["web01.corp.example.com", "web01", "db01"]
    assert "DeviceTvmInfoGathering" in query
    assert 'ConfigurationId == "scid-2011"' in query


@pytest.mark.parametrize("name", ['web01") | take 1 //', "web 01", "-web01", "a\\b", ""])
def test_names_that_are_not_host_names_are_refused_before_any_query(name):
    with pytest.raises(InputError):
        av_query([name])


def test_no_names_is_an_input_error():
    with pytest.raises(InputError, match="no devices named"):
        av_query([])


def test_statuses_match_names_in_order_on_the_fqdn_or_short_name():
    result = QueryResult.from_records(
        [row("db01.corp.example.com", AvMode="1", SignatureUpToDate=False), row("web01")]
    )
    statuses = av_statuses(["web01.corp.example.com", "db01", "ghost"], result)
    assert [(s.query, s.found, s.device_name) for s in statuses] == [
        ("web01.corp.example.com", True, "web01"),
        ("db01", True, "db01.corp.example.com"),
        ("ghost", False, ""),
    ]
    web, db, _ = statuses
    assert (web.signature, web.engine, web.platform, web.mode) == (
        "1.419.120.0",
        "1.1.24080.9",
        "4.18.24080.9",
        "active",
    )
    assert web.up_to_date is True
    assert web.reported.isoformat() == "2026-09-24T08:00:00+00:00"
    assert (db.mode, db.up_to_date) == ("passive", False)


def test_a_name_on_several_devices_shows_each_newest_first():
    result = QueryResult.from_records(
        [
            row("web01", Reported="2026-08-01T00:00:00Z", DeviceId="old"),
            row("web01", Reported="2026-09-01T00:00:00Z", DeviceId="new"),
        ]
    )
    assert [s.device_id for s in av_statuses(["web01"], result)] == ["new", "old"]


def test_an_unknown_freshness_or_mode_is_kept_as_it_came():
    result = QueryResult.from_records([row("web01", SignatureUpToDate=None, AvMode="7")])
    status = av_statuses(["web01"], result)[0]
    assert (status.up_to_date, status.mode) == (None, "7")
    assert (mode_label(None), mode_label(" 4 ")) == ("", "EDR block")


def test_versions_compare_as_numbers_not_text():
    assert version_key("1.419.99.0") < version_key("1.419.100.0")
    with pytest.raises(InputError, match="not a version number"):
        version_key("latest")
    result = QueryResult.from_records([row("web01"), row("web02", signature="")])
    web01, web02 = av_statuses(["web01", "web02"], result)
    assert web01.older_than("1.419.121.0")
    assert not web01.older_than("1.419.120.0")
    assert web02.older_than("1.0")  # an unknown signature is never new enough
