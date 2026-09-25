"""Small helpers shared across the subpackages: names, OData literals, timestamps."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from libre_devops_helpers.core.errors import InputError

_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
# What a host name can hold (letters, digits, dots, hyphens and underscores), and no more,
# so a name checked by require_host is safe inside a query's string literal.
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}")
# Some Microsoft APIs return seven fractional digits; datetime accepts six.
_LONG_FRACTION = re.compile(r"\.(\d{6})\d+")


def is_guid(value: str) -> bool:
    """True when ``value`` is a GUID in the 8-4-4-4-12 form."""
    return bool(_GUID.fullmatch(value.strip()))


def require_guid(value: str, what: str, *, hint: str | None = None) -> str:
    """``value`` as a lowercase GUID, else an InputError saying ``not {what}``.

    An id that goes into a URL path or a filter comes through here first, so a path is
    never built from anything else. ``what`` names it, with its article: "an object id".
    """
    if not is_guid(value):
        raise InputError(f"not {what}: {value!r}", hint=hint)
    return value.strip().lower()


def short_name(name: str) -> str:
    """The host part of a name: ``web01.corp.example.com`` -> ``web01``."""
    return name.strip().rstrip(".").split(".", 1)[0]


def require_host(value: str) -> str:
    """``value`` as a device name that can go into a query, else an InputError.

    Only the characters a host name holds are let in, so no quote, space or operator
    can reach the query around it. A trailing dot (an absolute FQDN) is dropped.
    """
    name = value.strip().rstrip(".")
    if not _HOST.fullmatch(name):
        raise InputError(
            f"{value!r} is not a device name that can go in a query",
            hint="use the host name or FQDN, e.g. web01 or web01.corp.example",
        )
    return name


def candidate_names(name: str) -> list[str]:
    """Names to try for one device, most specific first: the FQDN, then the short hostname.

    Entra and Defender do not record Linux host names consistently, so a lookup
    that misses on the FQDN retries on the short name.
    """
    full = name.strip().rstrip(".")
    short = short_name(full)
    return [full] if short.casefold() == full.casefold() else [full, short]


def split_names(values: Iterable[str]) -> list[str]:
    """Split comma- or whitespace-separated names, dropping blanks and repeats.

    ``["a,b", "c  d", "A"]`` -> ``["a", "b", "c", "d"]``: a command can take
    ``"X,Y,Z"`` as one argument, as several arguments, or as lines from a file.
    Repeats are matched case-insensitively and the first spelling is kept.
    """
    seen: set[str] = set()
    names: list[str] = []
    for value in values:
        for name in re.split(r"[,\s]+", value):
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
    return names


def odata_string(value: str) -> str:
    """Quote ``value`` as an OData string literal, doubling embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def odata_datetime(value: datetime) -> str:
    """A UTC OData datetime literal, ``2026-09-24T10:11:12Z``, which is never quoted."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp from an API into an aware UTC datetime.

    Returns None for empty or unparseable values rather than raising, because one
    odd record should not fail a whole listing.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = _LONG_FRACTION.sub(r".\1", value.strip())
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.year < 1900:
        # Microsoft APIs write 0001-01-01 (and, from Windows, 1601-01-01) for "not known".
        return None
    return parsed.astimezone(UTC)


_DURATION = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> timedelta:
    """Read ``90``, ``90s``, ``15m``, ``2h``, ``1h30m`` or ``7d`` as a duration.

    A bare number is seconds. Raises InputError for anything else, including zero.
    """
    value = text.strip().lower().replace(" ", "")
    if value.isdigit():
        seconds = int(value)
    else:
        parts = _DURATION.findall(value)
        if not parts or "".join(number + unit for number, unit in parts) != value:
            raise InputError(
                f"cannot read the duration {text!r}", hint="use e.g. 90, 90s, 15m, 2h, 1h30m or 7d"
            )
        seconds = sum(int(number) * _UNIT_SECONDS[unit] for number, unit in parts)
    if seconds <= 0:
        raise InputError(f"the duration {text!r} must be more than zero")
    return timedelta(seconds=seconds)


def format_span(delta: timedelta) -> str:
    """A span a person gave, as they would give it: ``7d``, ``12h`` or ``30m`` when it is a
    whole number of them, else as ``format_duration`` writes it."""
    seconds = int(delta.total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return format_duration(delta)


def format_duration(delta: timedelta) -> str:
    """Render a duration compactly: ``45s``, ``12m 05s``, ``3h 07m``, ``2d 04h``."""
    seconds = int(abs(delta.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"
