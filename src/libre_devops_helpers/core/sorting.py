"""Sorting and de-duplication that understand the values these APIs return.

``natural_key`` orders what a person would expect rather than what text order gives:

- numbers numerically: ``9.8`` before ``10.0``;
- versions part by part: ``1.419.99.0`` before ``1.419.100.0``;
- severities by rank: ``Informational``, ``Low``, ``Medium``, ``High``, ``Critical``;
- names naturally and without case: ``web2`` before ``web10``, ``Web3`` beside ``web3``;
- dates in time order, as datetimes or as ISO text (which that last rule gives).

``sort_records`` sorts on several keys, each ascending or descending, keeping blanks
(``None``, ``""``, ``-``) last either way; ``unique`` keeps the first of each value, so
sorting newest first and then keeping one per device keeps the newest record of each.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Iterable, Sequence
from datetime import date, datetime
from typing import Any, TypeVar

from libre_devops_helpers.core.errors import InputError

T = TypeVar("T")

SEVERITY_RANK = {
    "informational": 0,
    "info": 0,
    "none": 0,
    "low": 1,
    "medium": 2,
    "moderate": 2,
    "high": 3,
    "important": 3,
    "critical": 4,
}
BLANKS = frozenset({"", "-"})
_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?")
_VERSION = re.compile(r"\d+(\.\d+){2,}")
_PARTS = re.compile(r"(\d+)")


def blank(value: object) -> bool:
    """Whether a table would show ``value`` as nothing: None, empty, or ``-``."""
    return value is None or (isinstance(value, str) and value.strip() in BLANKS)


def natural_key(value: object) -> tuple[Any, ...]:
    """A key that orders ``value`` among others of its kind (see the module's list)."""
    if isinstance(value, datetime):
        return (0, value.timestamp())
    if isinstance(value, date):
        return (0, datetime(value.year, value.month, value.day).timestamp())
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int | float):
        return (1, float(value))
    text = str(value).strip()
    folded = text.casefold()
    if folded in SEVERITY_RANK:
        return (2, SEVERITY_RANK[folded])
    if _NUMBER.fullmatch(text):
        return (1, float(text))
    if _VERSION.fullmatch(text):
        return (3, tuple(int(part) for part in text.split(".")))
    return (
        4,
        tuple((0, int(part)) if part.isdigit() else (1, part) for part in _PARTS.split(folded)),
    )


def sort_records(
    items: Iterable[T], *keys: Callable[[T], object] | tuple[Callable[[T], object], bool]
) -> list[T]:
    """``items`` sorted by ``keys``, most significant first; ``(key, True)`` is descending.

    Stable, so records equal on every key keep their order, and blanks go last whichever
    way a key runs.
    """
    # Sorting by the least significant key first, then by each more significant one, gives
    # the order of all of them together, since each sort keeps ties in the order it found.
    ordered = list(items)
    for spec in reversed(keys):
        key, descending = spec if isinstance(spec, tuple) else (spec, False)
        ordered = _sorted_by(ordered, key, descending)
    return ordered


def _sorted_by(items: list[T], key: Callable[[T], object], descending: bool) -> list[T]:
    """``items`` by one key, with the blanks after the rest whichever way it runs."""
    present = [item for item in items if not blank(key(item))]
    missing = [item for item in items if blank(key(item))]
    present.sort(key=lambda item: natural_key(key(item)), reverse=descending)
    return present + missing


def unique(items: Iterable[T], key: Callable[[T], Hashable] | None = None) -> list[T]:
    """The first item for each value of ``key`` (the item itself by default), in order.

    Strings compare without case or surrounding space, so ``WEB01`` and ``web01 `` are one;
    a key of several values (a tuple) is one value, so rows unique on two columns work.
    """
    seen: set[Hashable] = set()
    kept: list[T] = []
    for item in items:
        marker = _fold(key(item) if key else item)
        if marker not in seen:
            seen.add(marker)
            kept.append(item)
    return kept


def _fold(value: Hashable) -> Hashable:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, tuple):
        return tuple(_fold(part) for part in value)
    return value


def parse_sort(spec: str) -> tuple[str, bool]:
    """``"last seen:desc"`` -> ("last seen", True). ``:asc`` or nothing is ascending."""
    name, _, direction = spec.rpartition(":") if ":" in spec else (spec, "", "asc")
    direction = direction.strip().casefold()
    if direction not in {"asc", "desc"} or not name.strip():
        raise InputError(
            f"cannot sort by {spec!r}", hint="use a column name, with :desc to reverse it"
        )
    return name.strip(), direction == "desc"


def column_index(headers: Sequence[str], name: str) -> int:
    """The column ``name`` names, ignoring case, spaces, hyphens and underscores."""
    wanted = _squash(name)
    for index, header in enumerate(headers):
        if _squash(header) == wanted:
            return index
    named = ", ".join(header for header in headers if header.strip())
    raise InputError(f"there is no {name!r} column", hint=f"columns: {named}")


def _squash(text: str) -> str:
    return re.sub(r"[\s_-]+", "", text).casefold()
