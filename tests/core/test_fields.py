from datetime import UTC, datetime

from libre_devops_helpers.core import fields


def test_text_is_empty_only_for_missing_or_null():
    data = {"name": "web01", "none": None, "zero": 0, "off": False, "empty": ""}
    assert fields.text(data, "name") == "web01"
    assert fields.text(data, "missing") == ""
    assert fields.text(data, "none") == ""
    # A falsy value is still a value: never swallowed into an empty string.
    assert fields.text(data, "zero") == "0"
    assert fields.text(data, "off") == "False"
    assert fields.text(data, "empty") == ""


def test_a_mapping_or_a_list_is_itself_else_empty():
    assert fields.mapping({"a": 1}) == {"a": 1}
    assert fields.mapping(None) == {}
    assert fields.mapping(["a"]) == {}
    assert fields.items([1, 2]) == [1, 2]
    assert fields.items({"a": 1}) == []
    assert fields.items(None) == []


def test_a_flag_is_true_false_or_not_known():
    assert fields.flag(True) is True
    assert fields.flag(False) is False
    for unknown in (None, "true", 1, 0):
        assert fields.flag(unknown) is None


def test_a_number_is_a_number_or_a_string_of_digits_never_a_boolean():
    assert fields.number(3) == 3.0
    assert fields.number(2.5) == 2.5
    assert fields.number(" 3599 ") == 3599.0
    for not_one in (True, False, None, "3.5", "soon", [1]):
        assert fields.number(not_one) is None


def test_a_date_is_utc_or_none_for_microsofts_not_known():
    data = {"at": "2026-09-24T12:00:00Z", "never": "0001-01-01T00:00:00Z", "bad": "soon"}
    assert fields.when(data, "at") == datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    assert fields.when(data, "never") is None
    assert fields.when(data, "bad") is None
    assert fields.when(data, "missing") is None
