"""Time windows for "what happened when": today, yesterday, the last 7d, or between two ends.

Days are local days: "today" starts at midnight where you are, and ``--from 2026-09-01
--to 2026-09-24`` covers both days whole. An end can be a moment instead, a day and a
time: ``--from 2026-09-24T09:00 --to 2026-09-24T12:30`` is those three and a half hours,
local time, or UTC with a ``Z`` (``2026-09-24T09:00Z``) or another offset. A window's
``start`` and ``end`` are timezone aware, so they convert cleanly to the UTC an API wants.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import format_span

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# A day and a time, with seconds and a UTC offset (Z, or +01:00) if wanted.
_MOMENT = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?", re.IGNORECASE
)


def local_now() -> datetime:
    """Now, in this machine's time zone."""
    return datetime.now().astimezone()


@dataclass(frozen=True)
class Window:
    """From ``start`` (inclusive) to ``end`` (exclusive); None is open-ended."""

    start: datetime | None
    end: datetime | None
    label: str

    def contains(self, when: datetime | None) -> bool:
        """Whether ``when`` falls in the window: from its start, up to but not including its end."""
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
    if _DAY.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InputError(
        f"{text!r} is not a day", hint="use YYYY-MM-DD, today or yesterday, or a time too"
    )


def choose_window(
    *,
    today: bool = False,
    yesterday: bool = False,
    since: timedelta | None = None,
    start: str | None = None,
    end: str | None = None,
    default: Callable[[datetime], Window] | None = None,
    now: datetime | None = None,
) -> Window:
    """The window the options name. Only one kind may be given; ``default`` otherwise.

    ``start`` and ``end`` are each a day (whole, so ``end`` includes it) or a moment, and
    either may be left out.
    """
    # With the real clock, midnights come from the system's own rules, so a window that
    # spans a clocks-change day still starts and ends at local midnight.
    zone = now.tzinfo if now is not None else None
    now = now or local_now()
    kinds = [today, yesterday, since is not None, bool(start or end)]
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
    if start or end:
        return _between(start, end, now, zone)
    return default(now) if default else Window(None, None, "all time")


@dataclass(frozen=True)
class _End:
    """One end of a ``--from`` / ``--to`` window, and how to say it."""

    at: datetime
    label: str


def _between(start: str | None, end: str | None, now: datetime, zone: tzinfo | None) -> Window:
    first = _end(start, now, zone, closing=False) if start else None
    final = _end(end, now, zone, closing=True) if end else None
    if first and final and first.at >= final.at:
        raise InputError(f"--from {first.label} is after --to {final.label}")
    if first and final:
        # One label when both ends are the same day: --from 2026-09-20 --to 2026-09-20.
        return Window(first.at, final.at, " to ".join(dict.fromkeys((first.label, final.label))))
    if first:
        return Window(first.at, None, f"from {first.label}")
    if final:
        return Window(None, final.at, f"up to {final.label}")
    return Window(None, None, "all time")


def _end(text: str, now: datetime, zone: tzinfo | None, *, closing: bool) -> _End:
    """A moment as it is (local time unless it says otherwise), or a day whole: from its
    midnight, or, as the ``closing`` end, up to the next."""
    value = text.strip()
    if _MOMENT.fullmatch(value):
        try:
            moment = datetime.fromisoformat(value.upper().replace(" ", "T"))
        except ValueError:
            raise InputError(f"{text!r} is not a time", hint="use YYYY-MM-DDTHH:MM") from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=zone) if zone else moment.astimezone()
        # As typed, but always the same way: 2026-09-24 09:00, or 2026-09-24 08:00Z.
        return _End(moment, value.upper().replace("T", " "))
    day = parse_day(value, today=now.date())
    return _End(_midnight(day + timedelta(days=1) if closing else day, zone), str(day))


def day_window(day: date, zone: tzinfo | None, label: str | None = None) -> Window:
    """The whole of ``day``, midnight to midnight, in ``zone``."""
    return Window(_midnight(day, zone), _midnight(day + timedelta(days=1), zone), label or f"{day}")


def last(span: timedelta, now: datetime) -> Window:
    """The ``span`` up to ``now``."""
    return Window(now - span, None, f"the last {format_span(span)}")


def today_window(now: datetime) -> Window:
    """From midnight today, local time, with no end."""
    return day_window(now.date(), now.tzinfo, "today")


def _midnight(day: date, zone: tzinfo | None) -> datetime:
    if zone is None:
        return datetime.combine(day, time.min).astimezone()  # local rules for that day
    return datetime.combine(day, time.min, tzinfo=zone)
