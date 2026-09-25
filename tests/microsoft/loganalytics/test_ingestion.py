from datetime import UTC, datetime, timedelta

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.microsoft.loganalytics import (
    TableIngestion,
    by_quietest,
    ingestion_query,
    read_ingestion,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
COLUMNS = ["DataType", "LastData", "Megabytes", "BillableMegabytes", "Solutions"]


def result(*rows):
    return QueryResult.from_columns(COLUMNS, rows)


def test_the_query_reads_usage_over_whole_hours():
    query = ingestion_query(timedelta(days=30))
    assert query.startswith("Usage\n| where TimeGenerated > ago(720h)")
    assert "by DataType" in query
    assert "ago(1h)" in ingestion_query(timedelta(minutes=90))
    for bad in (timedelta(minutes=30), timedelta(days=731)):
        with pytest.raises(InputError, match="from 1 hour to 730 days"):
            ingestion_query(bad)


def test_rows_become_tables_in_gigabytes_with_their_solutions():
    (table,) = read_ingestion(
        result(
            ["SecurityEvent", "2026-09-25T11:00:00Z", 2500.0, 2000.0, "Security, SecurityCenter"]
        )
    )
    assert table == TableIngestion(
        "SecurityEvent",
        datetime(2026, 9, 25, 11, tzinfo=UTC),
        2.5,
        2.0,
        ("Security", "SecurityCenter"),
    )
    assert table.quiet_for(NOW) == timedelta(hours=1)
    assert not table.quiet(NOW, timedelta(hours=24))
    assert read_ingestion(result(["", None, 0, 0, ""])) == []


def test_quiet_tables_come_first_the_longest_quiet_first_then_the_largest():
    tables = read_ingestion(
        result(
            ["Heartbeat", "2026-09-25T11:00:00Z", 10.0, 0.0, "LogManagement"],
            ["CommonSecurityLog", "2026-09-20T08:00:00Z", 5000.0, 5000.0, "Security"],
            ["Syslog", "2026-09-23T08:00:00Z", 900.0, 900.0, "LogManagement"],
            ["AzureActivity", "2026-09-25T10:00:00Z", 50.0, 0.0, "LogManagement"],
        )
    )
    ordered = [table.table for table in by_quietest(tables, NOW, timedelta(hours=24))]
    assert ordered == ["CommonSecurityLog", "Syslog", "AzureActivity", "Heartbeat"]


def test_a_table_with_no_time_is_never_called_quiet():
    (table,) = read_ingestion(result(["Odd", None, 1.0, 1.0, ""]))
    assert (table.quiet_for(NOW), table.quiet(NOW, timedelta(0))) == (None, False)
