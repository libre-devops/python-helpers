from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.timewindow import (
    Window,
    choose_window,
    day_window,
    last,
    parse_day,
    today_window,
)

BST = timezone(timedelta(hours=1))
NOW = datetime(2026, 9, 24, 15, 30, tzinfo=BST)


def test_today_and_yesterday_are_local_days():
    today = choose_window(today=True, now=NOW)
    assert (today.start, today.end, today.label) == (
        datetime(2026, 9, 24, tzinfo=BST),
        datetime(2026, 9, 25, tzinfo=BST),
        "today",
    )
    # In UTC, today began at 23:00 the day before.
    assert today.start.astimezone(UTC) == datetime(2026, 9, 23, 23, tzinfo=UTC)
    yesterday = choose_window(yesterday=True, now=NOW)
    assert yesterday.start == datetime(2026, 9, 23, tzinfo=BST)
    assert yesterday.label == "yesterday"


def test_since_is_the_span_up_to_now():
    window = choose_window(since=timedelta(days=7), now=NOW)
    assert (window.start, window.end, window.label) == (
        NOW - timedelta(days=7),
        None,
        "the last 7d",
    )
    assert last(timedelta(hours=6), NOW).label == "the last 6h"
    assert last(timedelta(minutes=90), NOW).label == "the last 90m"


def test_between_days_takes_both_days_whole():
    window = choose_window(start_day="2026-09-01", end_day="2026-09-03", now=NOW)
    assert window.start == datetime(2026, 9, 1, tzinfo=BST)
    assert window.end == datetime(2026, 9, 4, tzinfo=BST)
    assert window.label == "2026-09-01 to 2026-09-03"
    assert choose_window(start_day="yesterday", end_day="today", now=NOW).label == (
        "2026-09-23 to 2026-09-24"
    )
    assert (
        choose_window(start_day="2026-09-20", end_day="2026-09-20", now=NOW).label == "2026-09-20"
    )


def test_either_end_may_be_left_open():
    from_only = choose_window(start_day="2026-09-20", now=NOW)
    assert (from_only.end, from_only.label) == (None, "from 2026-09-20")
    to_only = choose_window(end_day="2026-09-20", now=NOW)
    assert (to_only.start, to_only.label) == (None, "up to 2026-09-20")


def test_the_default_applies_when_no_window_is_given():
    assert choose_window(default=today_window, now=NOW).label == "today"
    assert choose_window(now=NOW) == Window(None, None, "all time")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"today": True, "yesterday": True}, "choose one time window"),
        ({"today": True, "start_day": "2026-09-01"}, "choose one time window"),
        ({"start_day": "2026-09-05", "end_day": "2026-09-01"}, "is after"),
        ({"start_day": "last tuesday"}, "is not a day"),
        ({"start_day": "2026-02-30"}, "is not a day"),
    ],
)
def test_bad_windows_are_refused(options, message):
    with pytest.raises(InputError, match=message):
        choose_window(now=NOW, **options)


def test_contains_is_inclusive_at_the_start_and_exclusive_at_the_end():
    window = day_window(date(2026, 9, 24), BST)
    assert window.contains(datetime(2026, 9, 24, tzinfo=BST))
    assert not window.contains(datetime(2026, 9, 25, tzinfo=BST))
    assert not window.contains(None)
    assert Window(None, None, "all").contains(NOW)


def test_the_real_clock_uses_local_midnight():
    window = choose_window(today=True)
    assert window.start.hour == 0
    assert window.start.tzinfo is not None


def test_parse_day_names_and_dates():
    today = date(2026, 9, 24)
    assert parse_day("Today", today=today) == today
    assert parse_day("yesterday", today=today) == date(2026, 9, 23)
    assert parse_day("2026-01-02", today=today) == date(2026, 1, 2)
