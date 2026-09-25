"""Which tables a workspace is receiving: when each last got data, and how much.

This reads the workspace's ``Usage`` table, which holds one record per table (its
``DataType``) for each hour something was ingested. That makes it cheap to ask, since it
never reads the tables themselves, and accurate to the hour, not the event. It also means:

- a table that received nothing in the whole window is not listed at all, since nothing
  says it exists, so the window defaults to 30 days, long enough for a table that went
  quiet last week to show, as quiet;
- ``Usage`` itself arrives a little behind (up to an hour or so), so being quiet for less
  than a couple of hours is not a sign of anything.

Sizes are as ``Usage`` counts them, in gigabytes of 1000 MB; billable excludes the free
tables and data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult

DEFAULT_WINDOW = timedelta(days=30)
DEFAULT_QUIET_AFTER = timedelta(hours=24)
# Usage keeps what the workspace keeps; two years is the most a workspace does.
MAX_WINDOW = timedelta(days=730)

_QUERY = """\
Usage
| where TimeGenerated > ago({hours}h)
| summarize LastData = max(EndTime), Megabytes = sum(Quantity),
    BillableMegabytes = sumif(Quantity, IsBillable == true),
    Solutions = strcat_array(make_set(Solution, 10), ", ")
    by DataType
| order by Megabytes desc"""


@dataclass(frozen=True)
class TableIngestion:
    """One table's ingestion over the window: when it last received data (to the hour),
    how much it received, how much of that is billable, and the solutions that send it."""

    table: str
    last_data: datetime | None
    gigabytes: float
    billable_gigabytes: float
    solutions: tuple[str, ...]

    def quiet_for(self, now: datetime) -> timedelta | None:
        """How long since the table last received data, or None when that is not known."""
        return None if self.last_data is None else max(now - self.last_data, timedelta(0))

    def quiet(self, now: datetime, after: timedelta) -> bool:
        """Whether the table has received nothing for longer than ``after``."""
        silence = self.quiet_for(now)
        return silence is not None and silence > after


def ingestion_query(window: timedelta = DEFAULT_WINDOW) -> str:
    """The KQL: each table's last data, and its size, over ``window`` (whole hours)."""
    hours = int(window.total_seconds() // 3600)
    if not 1 <= hours <= MAX_WINDOW.total_seconds() // 3600:
        raise InputError("the window must be from 1 hour to 730 days", hint="e.g. 30d")
    return _QUERY.format(hours=hours)


def read_ingestion(result: QueryResult) -> list[TableIngestion]:
    """``result`` (of ``ingestion_query``) as one entry per table, largest first."""
    return [_table(row) for row in result.rows if fields.text(row, "DataType")]


def by_quietest(
    tables: Iterable[TableIngestion], now: datetime, after: timedelta
) -> list[TableIngestion]:
    """Quiet tables first, the longest quiet first; then the rest, largest first."""
    listed = list(tables)
    quiet = sorted(
        (table for table in listed if table.quiet(now, after)),
        key=lambda table: table.last_data or datetime.min.replace(tzinfo=UTC),
    )
    rest = sorted(
        (table for table in listed if not table.quiet(now, after)),
        key=lambda table: table.gigabytes,
        reverse=True,
    )
    return quiet + rest


def _table(data: Mapping[str, Any]) -> TableIngestion:
    solutions = fields.text(data, "Solutions")
    return TableIngestion(
        table=fields.text(data, "DataType"),
        last_data=fields.when(data, "LastData"),
        gigabytes=(fields.number(data.get("Megabytes")) or 0.0) / 1000,
        billable_gigabytes=(fields.number(data.get("BillableMegabytes")) or 0.0) / 1000,
        solutions=tuple(item.strip() for item in solutions.split(",") if item.strip()),
    )
