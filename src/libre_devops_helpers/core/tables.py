"""Tabular query results: one shape for Advanced Hunting, Resource Graph and Log Analytics.

Each of those APIs returns rows and columns in its own layout; each module converts
its reply into a ``QueryResult`` so the CLI renders all three the same way.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryResult:
    """Rows keyed by column name, with the columns in the order the query produced them.

    ``truncated`` is true when more rows existed than were fetched. ``warnings`` carries
    anything the service said about a partial result.
    """

    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    truncated: bool = False
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_records(
        cls, records: Iterable[Mapping[str, Any]], *, truncated: bool = False
    ) -> QueryResult:
        """Build from a list of objects, taking columns in first-seen order."""
        rows = tuple(dict(record) for record in records)
        columns: dict[str, None] = {}
        for row in rows:
            columns.update(dict.fromkeys(row))
        return cls(tuple(columns), rows, truncated)

    @classmethod
    def from_columns(
        cls,
        columns: Sequence[str],
        values: Iterable[Sequence[Any]],
        *,
        truncated: bool = False,
    ) -> QueryResult:
        """Build from column names plus rows of values in that column order."""
        names = tuple(columns)
        rows = tuple(dict(zip(names, row, strict=False)) for row in values)
        return cls(names, rows, truncated)
