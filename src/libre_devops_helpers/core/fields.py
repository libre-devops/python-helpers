"""Reading fields out of an API's JSON, the same way in every model.

APIs leave fields out, send null, and now and then send another type than they document.
Every model's ``from_json`` reads its fields through these, so a missing or odd value
becomes a plain default (an empty string, an empty mapping or list, None) rather than an
exception, or the text "None" in a table.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from libre_devops_helpers.core.util import parse_datetime


def text(data: Mapping[str, Any], key: str) -> str:
    """``data[key]`` as text: empty when it is missing or null, else ``str`` of it, so a
    ``0`` is "0" and a ``false`` "False" rather than nothing."""
    value = data.get(key)
    return "" if value is None else str(value)


def mapping(value: object) -> Mapping[str, Any]:
    """``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, Mapping) else {}


def items(value: object) -> list[Any]:
    """``value`` when it is a JSON array, else an empty one."""
    return value if isinstance(value, list) else []


def flag(value: object) -> bool | None:
    """``value`` when it is true or false; None when it is missing, null or anything else."""
    return value if isinstance(value, bool) else None


def number(value: object) -> float | None:
    """``value`` as a number: an integer or a float (a boolean is not one), or a string
    of digits, as some token endpoints send ``expires_in``; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip().isdigit():
        return float(value.strip())
    return None


def when(data: Mapping[str, Any], key: str) -> datetime | None:
    """``data[key]`` as a UTC datetime, or None when it is missing, unreadable or one of
    Microsoft's "not known" dates (``0001-01-01``)."""
    return parse_datetime(data.get(key))
