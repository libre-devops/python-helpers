from datetime import UTC, date, datetime
from operator import itemgetter

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.sorting import (
    blank,
    column_index,
    natural_key,
    parse_sort,
    sort_records,
    unique,
)


def ordered(values):
    return sorted(values, key=natural_key)


def test_numbers_sort_as_numbers_not_text():
    assert ordered(["10.0", "9.8", "-1", "100", 2, 7.5]) == ["-1", 2, 7.5, "9.8", "10.0", "100"]


def test_versions_sort_part_by_part():
    assert ordered(["1.419.100.0", "1.419.99.0", "1.2.3"]) == [
        "1.2.3",
        "1.419.99.0",
        "1.419.100.0",
    ]


def test_severities_sort_by_rank_whatever_their_case():
    words = ["High", "low", "Critical", "Informational", "MEDIUM", "Moderate", "Important"]
    assert ordered(words) == [
        "Informational",
        "low",
        "MEDIUM",
        "Moderate",
        "High",
        "Important",
        "Critical",
    ]


def test_names_sort_naturally_and_without_case():
    assert ordered(["web10", "Web3", "web2", "db01", "web2a"]) == [
        "db01",
        "web2",
        "web2a",
        "Web3",
        "web10",
    ]


def test_dates_sort_in_time_order():
    text = ["2026-09-24 14:05 (1h ago)", "2026-09-04 09:00 (20d ago)", "2025-12-31 23:59"]
    assert ordered(text) == [text[2], text[1], text[0]]
    when = [datetime(2026, 9, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)]
    assert ordered(when) == [when[1], when[0]]
    assert ordered([date(2026, 3, 1), date(2025, 3, 1)]) == [date(2025, 3, 1), date(2026, 3, 1)]


def test_values_of_different_kinds_never_fail_to_compare():
    mixed = ["web01", 3, "High", "1.2.3", True, datetime(2026, 1, 1, tzinfo=UTC), "x10y"]
    assert len(ordered(mixed)) == len(mixed)


def test_blanks_are_none_empty_and_a_dash():
    assert all(blank(value) for value in (None, "", " ", "-", " - "))
    assert not any(blank(value) for value in ("0", 0, "--", "web01"))


def test_records_sort_on_several_keys_with_blanks_last_either_way():
    rows = [
        {"cve": "CVE-1", "severity": "Low", "cvss": "3.1"},
        {"cve": "CVE-2", "severity": "Critical", "cvss": "9.1"},
        {"cve": "CVE-3", "severity": "-", "cvss": "5.0"},
        {"cve": "CVE-4", "severity": "Critical", "cvss": "9.8"},
        {"cve": "CVE-5", "severity": "Low", "cvss": None},
    ]
    down = sort_records(rows, (itemgetter("severity"), True), (itemgetter("cvss"), True))
    assert [row["cve"] for row in down] == ["CVE-4", "CVE-2", "CVE-1", "CVE-5", "CVE-3"]
    up = sort_records(rows, itemgetter("severity"), itemgetter("cvss"))
    assert [row["cve"] for row in up] == ["CVE-1", "CVE-5", "CVE-2", "CVE-4", "CVE-3"]


def test_sorting_is_stable_and_without_keys_keeps_the_order():
    rows = [("b", 1), ("a", 1), ("c", 0)]
    assert sort_records(rows, itemgetter(1)) == [("c", 0), ("b", 1), ("a", 1)]
    assert sort_records(iter(rows)) == rows


def test_unique_keeps_the_first_of_each_ignoring_case_and_space():
    assert unique(["WEB01", "web01 ", "db01", "DB01", "app07"]) == ["WEB01", "db01", "app07"]
    assert unique([]) == []


def test_unique_by_a_key_after_sorting_keeps_the_newest():
    seen = [
        {"device": "web01", "at": "2026-09-01"},
        {"device": "WEB01", "at": "2026-09-20"},
        {"device": "db01", "at": "2026-09-10"},
    ]
    newest = unique(sort_records(seen, (itemgetter("at"), True)), itemgetter("device"))
    assert newest == [seen[1], seen[2]]


def test_unique_on_several_values_keeps_each_combination():
    pairs = [("web01", "CVE-1"), ("Web01", "cve-1"), ("web01", "CVE-2"), ("db01", "CVE-1")]
    assert unique(pairs) == [pairs[0], pairs[2], pairs[3]]
    assert unique([1, 1, None, None, 2]) == [1, None, 2]


def test_sort_specs_name_a_column_and_a_direction():
    assert parse_sort("last seen:desc") == ("last seen", True)
    assert parse_sort(" CVSS : DESC ") == ("CVSS", True)
    assert parse_sort("name:asc") == ("name", False)
    assert parse_sort("name") == ("name", False)
    for bad in ("name:sideways", ":desc", ""):
        with pytest.raises(InputError, match="cannot sort by"):
            parse_sort(bad)


def test_columns_are_found_ignoring_case_spaces_and_underscores():
    headers = ["DEVICE", "", "LAST SEEN", "OBJECT ID"]  # an unheaded marker column, too
    assert column_index(headers, "last seen") == 2
    assert column_index(headers, "last_seen") == 2
    assert column_index(headers, "LastSeen") == 2
    assert column_index(headers, "object-id") == 3
    with pytest.raises(InputError, match="no 'owner' column") as caught:
        column_index(headers, "owner")
    assert caught.value.hint == "columns: DEVICE, LAST SEEN, OBJECT ID"
