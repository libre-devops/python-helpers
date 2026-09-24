from datetime import UTC, datetime, timedelta, timezone

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import (
    candidate_names,
    format_duration,
    is_guid,
    odata_datetime,
    odata_string,
    parse_datetime,
    parse_duration,
    short_name,
    split_names,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("web01.corp.example.com", ["web01.corp.example.com", "web01"]),
        ("web01.corp.example.com.", ["web01.corp.example.com", "web01"]),
        (" web01 ", ["web01"]),
    ],
)
def test_candidate_names_tries_fqdn_then_short_name(name, expected):
    assert candidate_names(name) == expected


def test_short_name():
    assert short_name("DB01.Example.com") == "DB01"


def test_split_names_accepts_commas_whitespace_and_drops_repeats():
    assert split_names(["web01,web02", "db01  db02", "WEB01", ","]) == [
        "web01",
        "web02",
        "db01",
        "db02",
    ]


def test_odata_string_doubles_single_quotes():
    assert odata_string("o'brien") == "'o''brien'"


def test_parse_datetime_handles_seven_fraction_digits_and_z():
    parsed = parse_datetime("2026-09-24T10:11:12.1234567Z")
    assert parsed == datetime(2026, 9, 24, 10, 11, 12, 123456, tzinfo=UTC)


def test_parse_datetime_treats_naive_as_utc_and_rejects_junk():
    assert parse_datetime("2026-09-24T10:11:12") == datetime(2026, 9, 24, 10, 11, 12, tzinfo=UTC)
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None
    assert parse_datetime("") is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=45), "45s"),
        (timedelta(minutes=12, seconds=5), "12m 05s"),
        (timedelta(hours=3, minutes=7), "3h 07m"),
        (timedelta(days=2, hours=4), "2d 04h"),
        (timedelta(seconds=-90), "1m 30s"),
    ],
)
def test_format_duration(delta, expected):
    assert format_duration(delta) == expected


def test_is_guid():
    assert is_guid("11111111-1111-1111-1111-11111111AAAA")
    assert not is_guid("web01")


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("90", 90), ("90s", 90), ("15m", 900), ("2h", 7200), ("1h30m", 5400), ("7d", 604800)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == timedelta(seconds=seconds)


@pytest.mark.parametrize("text", ["", "0", "0m", "soon", "5x", "1h 30", "-5m"])
def test_parse_duration_rejects_junk_and_zero(text):
    with pytest.raises(InputError):
        parse_duration(text)


def test_odata_datetime_is_utc_with_a_z():
    local = datetime(2026, 9, 24, 13, 0, tzinfo=timezone(timedelta(hours=1)))
    assert odata_datetime(local) == "2026-09-24T12:00:00Z"
