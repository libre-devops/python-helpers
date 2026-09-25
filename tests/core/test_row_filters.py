from datetime import date

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.row_filters import examples, parse_conditions, row_test

TODAY = date(2026, 9, 25)
HEADER = ["Server", "Scheduled Date", "Environment", "Status"]


def kept(where, rows, header=HEADER):
    test = row_test(parse_conditions(where, today=TODAY), header, rows, "plan.csv")
    return [row[0] for row in rows if test(row)]


def test_a_value_matches_as_text_whatever_the_case_and_spaces():
    rows = [["web01", "", " DEV ", ""], ["web02", "", "Prod", ""]]
    assert kept(["environment=dev"], rows) == ["web01"]


def test_one_columns_values_are_alternatives_and_every_column_must_match():
    rows = [
        ["web01", "2026-09-25", "Dev", "Done"],
        ["web02", "2026-09-25", "Prod", ""],
        ["web03", "2026-09-26", "Dev", ""],
        ["web04", "2026-09-25", "Test", ""],
    ]
    where = ["Scheduled Date=today", "Environment=Dev", "Environment=Test", "Status!=Done"]
    assert kept(where, rows) == ["web04"]


def test_an_empty_value_matches_a_blank_cell():
    rows = [["web01", "", "", "Done"], ["web02", "", "", ""]]
    assert kept(["Status="], rows) == ["web02"]
    assert kept(["Status!="], rows) == ["web01"]


@pytest.mark.parametrize(
    ("value", "day"),
    [
        ("today", "2026-09-25"),
        ("Tomorrow", "2026-09-26"),
        ("yesterday", "2026-09-24"),
        ("2026-09-26", "2026-09-26"),
        ("26/09/2026", "2026-09-26"),  # UK: day over 12
        ("09/26/2026", "2026-09-26"),  # US: day over 12
        ("5/5/2026", "2026-05-05"),  # the same either way
    ],
)
def test_a_date_matches_a_cell_holding_that_day(value, day):
    rows = [
        ["web01", day, "", ""],
        ["web02", f"{day}T09:00:00", "", ""],
        ["web03", "2020-01-01", "", ""],
    ]
    assert kept([f"Scheduled Date={value}"], rows) == ["web01", "web02"]


SEPTEMBER = [
    ["web01", "2026-09-01"],
    ["web02", "2026-09-14"],
    ["web03", "2026-09-15"],
    ["web04", "2026-09-25T09:00:00"],
    ["web05", ""],
]
DATED = ["Server", "Scheduled Date"]


@pytest.mark.parametrize(
    ("value", "servers"),
    [
        ("2026-09-01..2026-09-14", ["web01", "web02"]),  # both ends included
        ("01/09/2026..14/09/2026", ["web01", "web02"]),  # UK, which the 14 says
        ("09/01/2026..09/14/2026", ["web01", "web02"]),  # US, which the 14 says
        ("..2026-09-14", ["web01", "web02"]),
        ("2026-09-15..", ["web03", "web04"]),
        ("today..", ["web04"]),
        ("last 7d", ["web04"]),  # 19 to 25 September
        ("last 11d", ["web03", "web04"]),  # 15 to 25 September
        ("next 7d", ["web04"]),
        ("yesterday..tomorrow", ["web04"]),
    ],
)
def test_a_span_of_days_matches_every_day_in_it(value, servers):
    assert kept([f"Scheduled Date={value}"], SEPTEMBER, DATED) == servers


def test_spans_on_one_column_are_alternatives_and_one_can_leave_rows_out():
    where = ["Scheduled Date=2026-09-01..2026-09-01", "Scheduled Date=last 7d"]
    assert kept(where, SEPTEMBER, DATED) == ["web01", "web04"]
    assert kept(["Scheduled Date!=2026-09-01..2026-09-14"], SEPTEMBER, DATED) == [
        "web03",
        "web04",
        "web05",
    ]


def test_every_row_with_a_date_is_the_column_not_blank():
    assert kept(["Scheduled Date!="], SEPTEMBER, DATED) == ["web01", "web02", "web03", "web04"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("..", "names no days"),
        ("2026-09-14..2026-09-01", "ends before it starts"),
        ("last 0d", "is no days"),
        ("last 7", "is not a span of days"),
        ("next week", "is not a span of days"),
        ("2026-09-01..soon", "'soon' in '2026-09-01..soon' is not a date"),
        ("01/02/2026..03/04/2026", "could be a UK or a US date"),
    ],
    ids=["no-ends", "backwards", "no-days", "no-unit", "words", "not-a-date", "unclear"],
)
def test_a_span_that_cannot_be_read_is_refused(value, message):
    with pytest.raises(InputError, match=message):
        kept([f"Scheduled Date={value}"], SEPTEMBER, DATED)


def test_a_uk_column_reads_its_dates_and_an_unclear_value_the_uk_way():
    rows = [
        ["web01", "25/09/2026", "", ""],
        ["web02", "01/02/2026", "", ""],
        ["web03", "02/01/2026 09:00", "", ""],
    ]
    assert kept(["Scheduled Date=01/02/2026"], rows) == ["web02"]  # 1 February
    assert kept(["Scheduled Date=2026-01-02"], rows) == ["web03"]  # 2 January


def test_a_us_column_reads_its_dates_and_an_unclear_value_the_us_way():
    rows = [
        ["web01", "09/25/2026", "", ""],
        ["web02", "01/02/2026", "", ""],
        ["web03", "2/1/2026 9:00 AM", "", ""],
    ]
    assert kept(["Scheduled Date=01/02/2026"], rows) == ["web02"]  # 2 January
    assert kept(["Scheduled Date=2026-02-01"], rows) == ["web03"]  # 1 February


def test_a_column_holding_both_uk_and_us_dates_is_refused():
    rows = [["web01", "25/09/2026", "", ""], ["web02", "09/26/2026", "", ""]]
    with pytest.raises(
        InputError, match="holds both UK and US dates, such as 25/09/2026 and 09/26/2026"
    ):
        kept(["Scheduled Date=today"], rows)


def test_a_column_that_never_says_uk_or_us_is_refused():
    rows = [["web01", "01/02/2026", "", ""], ["web02", "03/04/2026", "", ""]]
    with pytest.raises(
        InputError, match=r"cannot tell whether the dates .* are UK or US, such as 01/02/2026"
    ) as caught:
        kept(["Scheduled Date=today"], rows)
    assert "YYYY-MM-DD" in (caught.value.hint or "")


def test_an_unclear_value_against_a_column_of_real_dates_is_refused_with_both_readings():
    rows = [["web01", "2026-02-01", "", ""]]
    with pytest.raises(InputError, match="could be a UK or a US date") as caught:
        kept(["Scheduled Date=01/02/2026"], rows)
    assert caught.value.hint == "write it as YYYY-MM-DD: 2026-02-01 or 2026-01-02"


def test_a_text_filter_is_not_troubled_by_unclear_dates_in_other_columns():
    rows = [["web01", "01/02/2026", "Dev", ""]]
    assert kept(["Environment=Dev"], rows) == ["web01"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Server", "is not COLUMN=VALUE"),
        ("=web01", "is not COLUMN=VALUE"),
        ("!=web01", "is not COLUMN=VALUE"),
        ("Scheduled Date=2026-02-30", "'2026-02-30' is not a date"),
        ("Scheduled Date=31/31/2026", "'31/31/2026' is not a date"),
    ],
    ids=["no-equals", "no-column", "no-column-negated", "no-such-iso-day", "no-such-day"],
)
def test_a_condition_that_cannot_be_read_is_refused(text, message):
    with pytest.raises(InputError, match=message):
        parse_conditions([text], today=TODAY)


def test_a_column_that_is_not_there_lists_the_columns():
    with pytest.raises(InputError, match="has no column 'Owner'") as caught:
        kept(["Owner=me"], [["web01", "", "", ""]])
    assert caught.value.hint == "columns: Server, Scheduled Date, Environment, Status"


def test_examples_are_a_few_of_a_columns_values_once_each():
    rows = [
        ["web01", "2026-09-25"],
        ["web02", "2026-09-25"],
        ["web03", ""],
        ["web04", "2026-09-26"],
    ]
    assert (
        examples(rows, ["Server", "Scheduled Date"], "scheduled date") == "2026-09-25, 2026-09-26"
    )
