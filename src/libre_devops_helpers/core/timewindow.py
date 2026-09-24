"""Time windows for "what happened when": today, yesterday, the last 7d, or between days.

Days are local days: "today" starts at midnight where you are, and ``--from 2026-09-01
--to 2026-09-24`` covers both days whole. A window's ``start`` and ``end`` are timezone
aware, so they convert cleanly to the UTC an API filter wants.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import format_duration

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def local_now() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True)
class Window:
    """From ``start`` (inclusive) to ``end`` (exclusive); None is open-ended."""

    start: datetime | None
    end: datetime | None
    label: str

    def contains(self, when: datetime | None) -> bool:
        if when is None:
            return False
        if self.start is not None and when < self.start:
            return False
        return not (self.end is not None and when >= self.end)


def parse_day(text: str, *, today: date) -> date:
    """``today``, ``yesterday`` or ``YYYY-MM-DD``."""
    value = text.strip().lower()
    if value == "today":
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    if _DAY.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InputError(f"{text!r} is not a day", hint="use YYYY-MM-DD, today or yesterday")


def choose_window(
    *,
    today: bool = False,
    yesterday: bool = False,
    since: timedelta | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
    default: Callable[[datetime], Window] | None = None,
    now: datetime | None = None,
) -> Window:
    """The window the options name. Only one kind may be given; ``default`` otherwise.

    ``start_day`` and ``end_day`` are inclusive, and either may be left out.
    """
    # With the real clock, midnights come from the system's own rules, so a window that
    # spans a clocks-change day still starts and ends at local midnight.
    zone = now.tzinfo if now is not None else None
    now = now or local_now()
    kinds = [today, yesterday, since is not None, bool(start_day or end_day)]
    if sum(kinds) > 1:
        raise InputError(
            "choose one time window",
            hint="--today, --yesterday, --since, or --from and --to",
        )
    if today:
        return day_window(now.date(), zone, "today")
    if yesterday:
        return day_window(now.date() - timedelta(days=1), zone, "yesterday")
    if since is not None:
        return last(since, now)
    if start_day or end_day:
        first = parse_day(start_day, today=now.date()) if start_day else None
        final = parse_day(end_day, today=now.date()) if end_day else None
        if first and final and first > final:
            raise InputError(f"--from {first} is after --to {final}")
        start = _midnight(first, zone) if first else None
        end = _midnight(final + timedelta(days=1), zone) if final else None
        if first and final:
            label = f"{first}" if first == final else f"{first} to {final}"
        else:
            label = f"from {first}" if first else f"up to {final}"
        return Window(start, end, label)
    return default(now) if default else Window(None, None, "all time")


def day_window(day: date, zone: tzinfo | None, label: str | None = None) -> Window:
    """The whole of ``day``, midnight to midnight, in ``zone``."""
    return Window(_midnight(day, zone), _midnight(day + timedelta(days=1), zone), label or f"{day}")


def last(span: timedelta, now: datetime) -> Window:
    """The ``span`` up to ``now``."""
    return Window(now - span, None, f"the last {_span(span)}")


def today_window(now: datetime) -> Window:
    return day_window(now.date(), now.tzinfo, "today")


def _midnight(day: date, zone: tzinfo | None) -> datetime:
    if zone is None:
        return datetime.combine(day, time.min).astimezone()  # local rules for that day
    return datetime.combine(day, time.min, tzinfo=zone)


def _span(delta: timedelta) -> str:
    """``7d``, ``12h`` or ``30m`` when it is a whole number of them."""
    seconds = int(delta.total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return format_duration(delta)
