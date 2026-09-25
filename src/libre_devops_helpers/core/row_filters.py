"""Which rows of a CSV or workbook to read names from: ``--where COLUMN=VALUE``.

    --where "Scheduled Date=tomorrow" --where "Environment=Dev"
    --where "Scheduled Date=2026-09-01..2026-09-14"
    --where "Scheduled Date=last 7d"

A condition is ``COLUMN=VALUE``, or ``COLUMN!=VALUE`` to leave rows out. Conditions on one
column are alternatives (any of its values will do); conditions on different columns must
all hold. Columns are found by header, and values compared as text, whatever their case and
the spaces around them.

A value that is a date, or a span of them, is compared as days:

- a day: ``today``, ``tomorrow``, ``yesterday``, ``2026-09-25``, or a UK or a US date
  (``25/09/2026``, ``09/25/2026``);
- ``FROM..TO``: the days from one to the other, both included, where either may be left
  out for no limit (``..2026-09-14``, ``today..``);
- ``last 7d`` (the seven days to today, today included) or ``next 7d`` (today and the six
  after).

A day matches a cell holding it: an Excel date cell (read as ``2026-09-25``, see
``core.excel_dates``), or text written one of those ways, with or without a time after it.
No other way of writing a date is read.

UK and US dates differ only when both numbers are 12 or under: 01/02/2026 is 1 February in
one and 2 January in the other. Nothing here guesses. A span says which it is written in
when either end has a number over 12, and so does a column once one of its dates has; a
value is read that way. A value nothing settles, a column that never says, and a column
holding both are refused, saying why.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from libre_devops_helpers.core.errors import InputError

Order = Literal["uk", "us"]
RowTest = Callable[[Sequence[str]], bool]

_RELATIVE = {"yesterday": -1, "today": 0, "tomorrow": 1}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?")
_SLASHED = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?)?"
)
_WINDOW = re.compile(r"(last|next)\s*(\d{1,4})d", re.IGNORECASE)
_EXAMPLES = 5
_SPAN_HINT = "e.g. 2026-09-01..2026-09-14, ..2026-09-14, today.., last 7d or next 7d"


@dataclass(frozen=True)
class Day:
    """A day as written: known already (ISO, or a keyword), or UK or US numbers not yet
    read, as ``(first, second, year)``."""

    known: date | None = None
    slashed: tuple[int, int, int] | None = None

    @property
    def order(self) -> Order | None:
        """UK or US, when the numbers alone say which."""
        return _order_shown(*self.slashed[:2]) if self.slashed else None

    def read(self, order: Order | None) -> date | None:
        """The day, reading slashed numbers as ``order`` when they alone cannot say which;
        None when they cannot, or are no real day."""
        if self.known is not None or self.slashed is None:
            return self.known
        first, second, year = self.slashed
        use = self.order or order or ("uk" if first == second else None)
        if use is None:
            return None
        day, month = (first, second) if use == "uk" else (second, first)
        try:
            return date(year, month, day)
        except ValueError:
            return None


@dataclass(frozen=True)
class Span:
    """The days from ``start`` to ``end``, both included; None at an end for no limit."""

    start: Day | None
    end: Day | None

    @property
    def order(self) -> Order | None:
        """UK or US, when either end says which."""
        return next((day.order for day in (self.start, self.end) if day and day.order), None)


@dataclass(frozen=True)
class Condition:
    """One ``COLUMN=VALUE`` (or ``!=``). ``days`` is set when the value is a date or a span."""

    text: str
    column: str
    value: str
    negated: bool = False
    days: Span | None = None


def parse_conditions(texts: Iterable[str], *, today: date) -> tuple[Condition, ...]:
    """Each ``COLUMN=VALUE`` or ``COLUMN!=VALUE``, with ``today`` for the relative days."""
    return tuple(_condition(text, today) for text in texts)


def row_test(
    conditions: Sequence[Condition],
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    source: str,
) -> RowTest:
    """A test of a row's cells against every condition, for the table with this ``header``;
    ``rows`` are all its rows, from which each date column's UK or US order is read."""
    wanted: dict[tuple[int, bool], list[Callable[[str], bool]]] = {}
    for condition in conditions:
        index = _index(header, condition.column, source)
        matcher = _matcher(condition, index, rows, source)
        wanted.setdefault((index, condition.negated), []).append(matcher)

    def test(cells: Sequence[str]) -> bool:
        for (index, negated), matchers in wanted.items():
            cell = cells[index].strip() if index < len(cells) else ""
            if any(match(cell) for match in matchers) == negated:
                return False
        return True

    return test


def examples(rows: Iterable[Sequence[str]], header: Sequence[str], column: str) -> str:
    """A few of the values a column holds, for a hint when no row matched."""
    wanted = column.strip().casefold()
    index = next(i for i, cell in enumerate(header) if cell.strip().casefold() == wanted)
    seen: dict[str, None] = {}
    for cells in rows:
        value = cells[index].strip() if index < len(cells) else ""
        if value:
            seen.setdefault(value)
        if len(seen) == _EXAMPLES:
            break
    return ", ".join(seen) or "nothing"


def written_day(text: str) -> Day | None:
    """``text`` as a day, when it is written one of the ways read here, else None."""
    iso = _ISO.fullmatch(text)
    if iso:
        try:
            return Day(known=date(*(int(part) for part in iso.groups())))
        except ValueError:
            return None
    slashed = _SLASHED.fullmatch(text)
    if slashed:
        first, second, year = (int(part) for part in slashed.groups())
        return Day(slashed=(first, second, year))
    return None


def _condition(text: str, today: date) -> Condition:
    at = text.find("=")
    negated = at > 0 and text[at - 1] == "!"
    column = text[: at - 1 if negated else at].strip() if at > 0 else ""
    if not column:
        raise InputError(
            f"--where {text!r} is not COLUMN=VALUE",
            hint='e.g. --where "Scheduled Date=tomorrow", or "Status!=Done" to leave rows out',
        )
    value = text[at + 1 :].strip()
    return Condition(text, column, value, negated, _value_days(value, today))


def _value_days(value: str, today: date) -> Span | None:
    """The days a value names: a span, a window, one day, or None when it is text."""
    window = _WINDOW.fullmatch(value)
    if window:
        return _window(window.group(1).casefold(), int(window.group(2)), today, value)
    if value.casefold().startswith(("last ", "next ")):
        raise InputError(f"{value!r} is not a span of days", hint=_SPAN_HINT)
    if ".." in value:
        start, _, end = value.partition("..")
        span = Span(_end(start, today, value), _end(end, today, value))
        if span.start is None and span.end is None:
            raise InputError(f"{value!r} names no days", hint=_SPAN_HINT)
        return span
    day = _day(value, today)
    return Span(day, day) if day else None


def _window(direction: str, count: int, today: date, value: str) -> Span:
    if count < 1:
        raise InputError(f"{value!r} is no days", hint=_SPAN_HINT)
    reach = timedelta(days=count - 1)
    if direction == "last":
        return Span(Day(known=today - reach), Day(known=today))
    return Span(Day(known=today), Day(known=today + reach))


def _end(text: str, today: date, value: str) -> Day | None:
    """One end of a span: a day, or None when left out."""
    if not text.strip():
        return None
    day = _day(text.strip(), today)
    if day is None:
        raise InputError(f"{text.strip()!r} in {value!r} is not a date", hint=_SPAN_HINT)
    return day


def _day(value: str, today: date) -> Day | None:
    """A keyword or a written date as a day; None when the value is not written as one."""
    offset = _RELATIVE.get(value.casefold())
    if offset is not None:
        return Day(known=today + timedelta(days=offset))
    looks_like_one = _ISO.fullmatch(value) or _SLASHED.fullmatch(value)
    if not looks_like_one:
        return None
    day = written_day(value)
    if day is None or (day.slashed and day.read("uk") is None and day.read("us") is None):
        raise InputError(f"{value!r} is not a date", hint="write it as YYYY-MM-DD, e.g. 2026-09-25")
    return day


def _order_shown(first: int, second: int) -> Order | None:
    if first > 12:
        return "uk"
    if second > 12:
        return "us"
    return None


def _index(header: Sequence[str], column: str, source: str) -> int:
    wanted = column.casefold()
    for index, cell in enumerate(header):
        if cell.strip().casefold() == wanted:
            return index
    raise InputError(
        f"{source} has no column {column!r} to filter on",
        hint=f"columns: {', '.join(cell for cell in header if cell.strip())}",
    )


def _matcher(
    condition: Condition, index: int, rows: Sequence[Sequence[str]], source: str
) -> Callable[[str], bool]:
    if condition.days is None:
        value = condition.value.casefold()
        return lambda cell: cell.casefold() == value
    order = _column_order(rows, index, condition.column, source)
    # A span written one way (01/09/2026..14/09/2026) reads both its ends that way.
    reading = condition.days.order or order
    start = _read_end(condition.days.start, reading, condition)
    end = _read_end(condition.days.end, reading, condition)
    if start is not None and end is not None and start > end:
        raise InputError(f"{condition.value!r} ends before it starts", hint=_SPAN_HINT)

    def matches(cell: str) -> bool:
        written = written_day(cell)
        day = written.read(order) if written else None
        return day is not None and (start is None or day >= start) and (end is None or day <= end)

    return matches


def _read_end(day: Day | None, order: Order | None, condition: Condition) -> date | None:
    if day is None:
        return None
    read = day.read(order)
    if read is None:
        raise InputError(
            f"{condition.value!r} could be a UK or a US date, and the column {condition.column!r} "
            "does not say which",
            hint=_both_ways(day),
        )
    return read


def _column_order(
    rows: Sequence[Sequence[str]], index: int, column: str, source: str
) -> Order | None:
    """Whether the column's slashed dates are UK or US, as the first over 12 says; None when
    it holds none. A column holding both, or never saying, is refused."""
    shown: dict[Order, str] = {}
    unsure = ""
    for cells in rows:
        cell = cells[index].strip() if index < len(cells) else ""
        day = written_day(cell)
        if day is None or day.slashed is None:
            continue
        if day.order is not None:
            shown.setdefault(day.order, cell)
        elif day.slashed[0] != day.slashed[1]:
            unsure = unsure or cell
    if len(shown) > 1:
        raise InputError(
            f"the column {column!r} of {source} holds both UK and US dates, such as "
            f"{shown['uk']} and {shown['us']}",
            hint="write them all one way, or as YYYY-MM-DD, or keep them as dates in Excel",
        )
    if shown:
        return next(iter(shown))
    if unsure:
        raise InputError(
            f"cannot tell whether the dates in the column {column!r} of {source} are UK or US, "
            f"such as {unsure}: none has a number over 12 to say which",
            hint="write them as YYYY-MM-DD, or keep them as dates in Excel",
        )
    return None


def _both_ways(day: Day) -> str:
    readings = [
        reading.isoformat() for reading in (day.read("uk"), day.read("us")) if reading is not None
    ]
    return f"write it as YYYY-MM-DD: {' or '.join(dict.fromkeys(readings))}"
