"""Excel's dates: which number formats show a cell as a date or a time, and what day it is.

Excel keeps a date as a number: the days since its epoch, with the time of day as the
fraction. Only the cell's number format makes 46290 look like 25/09/2026, so a reader that
wants what a person sees reads the format too. These give the day, the time or both as ISO
text (``2026-09-25``, ``09:00:00``, ``2026-09-25T09:00:00``), whatever the format showed,
so the same date reads the same from any workbook, whichever country saved it.

Two quirks are Excel's own: most workbooks count from 1900 and some old Mac ones from 1904,
and the 1900 count has a 29 February 1900 that never was (kept for Lotus 1-2-3).
"""

from __future__ import annotations

import math
import re
from datetime import date, time, timedelta
from typing import Literal

Kind = Literal["date", "time", "datetime"]

# The built-in formats (ECMA-376 part 1, 18.8.30) that show a date or a time, by id. 46
# ([h]:mm:ss) is an elapsed time, a length of time rather than a moment, so it is not one.
_BUILT_IN: dict[int, Kind] = {
    **dict.fromkeys((14, 15, 16, 17), "date"),
    **dict.fromkeys((18, 19, 20, 21, 45, 47), "time"),
    22: "datetime",
    # The East Asian date formats, which Excel numbers apart.
    **dict.fromkeys((*range(27, 37), *range(50, 59)), "date"),
}
# In a format code: literal text, an escaped character, and padding, none of which is a
# date part however it is spelled.
_LITERAL = re.compile(r'"[^"]*"|\\.|_.|\*.')
_BRACKETED = re.compile(r"\[([^\]]*)\]")
_ELAPSED = re.compile(r"[hms]+", re.IGNORECASE)
_EPOCH_1900 = date(1899, 12, 30)
_EPOCH_1900_EARLY = date(1899, 12, 31)  # for the days before the 29 February that never was
_EPOCH_1904 = date(1904, 1, 1)
_PHANTOM_DAY = 60


def format_kind(format_id: int, code: str | None = None) -> Kind | None:
    """What a cell with this number format shows: a date, a time, both, or neither (None).

    ``code`` is the format's code when the workbook defines it (ids from 164 on); a
    built-in format is known by its id alone.
    """
    if code is None:
        return _BUILT_IN.get(format_id)
    # The first section is the one for positive numbers, which dates are.
    section = _LITERAL.sub("", code.split(";", 1)[0])
    if any(_ELAPSED.fullmatch(inner) for inner in _BRACKETED.findall(section)):
        return None
    section = _BRACKETED.sub("", section).lower()  # colours, locales, conditions
    has_time = any(part in section for part in ("h", "s", "am/pm", "a/p"))
    section = section.replace("am/pm", "").replace("a/p", "")
    # m alone is a month (mmm yyyy); beside an h or an s it is a minute (hh:mm).
    has_date = "y" in section or "d" in section or ("m" in section and not has_time)
    if has_date and has_time:
        return "datetime"
    if has_date:
        return "date"
    return "time" if has_time else None


def from_serial(serial: float, kind: Kind, *, date1904: bool = False) -> str | None:
    """A cell's number as the ISO date, time or both its format shows, or None when it is no
    day there was (negative, too large, or the 29 February 1900 Excel counts)."""
    if not math.isfinite(serial) or serial < 0:
        return None
    days, seconds = divmod(round(serial * 86400), 86400)
    moment = time(seconds // 3600, seconds // 60 % 60, seconds % 60)
    if kind == "time":
        return moment.isoformat()
    day = _day(days, date1904)
    if day is None:
        return None
    return day.isoformat() if kind == "date" else f"{day.isoformat()}T{moment.isoformat()}"


def _day(days: int, date1904: bool) -> date | None:
    if date1904:
        epoch = _EPOCH_1904
    elif days == _PHANTOM_DAY:
        return None
    else:
        epoch = _EPOCH_1900_EARLY if days < _PHANTOM_DAY else _EPOCH_1900
    try:
        return epoch + timedelta(days=days)
    except OverflowError:
        return None
