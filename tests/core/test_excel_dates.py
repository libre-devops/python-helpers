import pytest

from libre_devops_helpers.core.excel_dates import format_kind, from_serial


@pytest.mark.parametrize(
    ("format_id", "code", "kind"),
    [
        (14, None, "date"),
        (17, None, "date"),
        (21, None, "time"),
        (22, None, "datetime"),
        (46, None, None),  # [h]:mm:ss, a length of time
        (0, None, None),  # General
        (2, None, None),  # 0.00
        (164, "dd/mm/yyyy", "date"),
        (164, "mm/dd/yyyy", "date"),
        (164, "[$-809]dd mmmm yyyy", "date"),
        (164, "mmm yy", "date"),
        (164, "hh:mm:ss", "time"),
        (164, "mm:ss", "time"),
        (164, "h:mm AM/PM", "time"),
        (164, "yyyy-mm-dd hh:mm", "datetime"),
        (164, "[h]:mm:ss", None),
        (164, "[mm]:ss", None),
        (164, "0.00E+00", None),
        (164, '"day" 0', None),
        (164, "#,##0.00;[Red]-#,##0.00", None),
        (164, "@", None),
    ],
)
def test_a_format_shows_a_date_a_time_both_or_neither(format_id, code, kind):
    assert format_kind(format_id, code) == kind


@pytest.mark.parametrize(
    ("serial", "kind", "shown"),
    [
        (46290, "date", "2026-09-25"),
        (46290.375, "date", "2026-09-25"),  # a date format shows no time
        (0.375, "time", "09:00:00"),
        (46290.375, "time", "09:00:00"),
        (46290.375, "datetime", "2026-09-25T09:00:00"),
        (46290.999999, "datetime", "2026-09-26T00:00:00"),  # rounded to the second
        (1, "date", "1900-01-01"),
        (59, "date", "1900-02-28"),
        (61, "date", "1900-03-01"),
        (60, "date", None),  # the 29 February 1900 Excel counts
        (-1, "date", None),
        (float("inf"), "date", None),
        (1e12, "date", None),
    ],
    ids=str,
)
def test_a_serial_is_the_day_excel_shows(serial, kind, shown):
    assert from_serial(serial, kind) == shown


def test_a_1904_workbook_counts_from_1904():
    assert from_serial(46290, "date", date1904=True) == "2030-09-26"
    assert from_serial(0, "date", date1904=True) == "1904-01-01"
