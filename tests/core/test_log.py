import json
import logging

import pytest

from libre_devops_helpers.core.log import (
    JsonFormatter,
    OtlpFormatter,
    normalise_format,
    resolve_level,
)
from libre_devops_helpers.core.tables import QueryResult


def record(
    message: str = "retrying in %.1fs", args: tuple = (1.5,), exc_info=None
) -> logging.LogRecord:
    return logging.LogRecord(
        "libre_devops_helpers.core.http",
        logging.WARNING,
        __file__,
        42,
        message,
        args,
        exc_info,
        func="_wait",
    )


def test_json_is_one_flat_object_per_line():
    data = json.loads(JsonFormatter().format(record()))
    assert data["level"] == "warning"
    assert data["message"] == "retrying in 1.5s"
    assert data["logger"].endswith("core.http")


def test_otlp_is_an_export_logs_service_request_with_otlp_json_encoding():
    line = OtlpFormatter(service_version="9.9.9").format(record())
    assert "\n" not in line
    request = json.loads(line)
    resource_logs = request["resourceLogs"][0]
    attributes = {item["key"]: item["value"] for item in resource_logs["resource"]["attributes"]}
    assert attributes["service.name"] == {"stringValue": "ldo"}
    assert attributes["service.version"] == {"stringValue": "9.9.9"}
    scope_logs = resource_logs["scopeLogs"][0]
    assert scope_logs["scope"]["name"].endswith("core.http")
    log_record = scope_logs["logRecords"][0]
    # OTLP JSON: 64-bit integers are strings, severityNumber is the integer.
    assert isinstance(log_record["timeUnixNano"], str)
    assert log_record["severityNumber"] == 13
    assert log_record["severityText"] == "WARNING"
    assert log_record["body"] == {"stringValue": "retrying in 1.5s"}
    code = {item["key"]: item["value"] for item in log_record["attributes"]}
    assert code["code.lineno"] == {"intValue": "42"}


def test_otlp_records_exceptions_as_semantic_attributes():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        line = OtlpFormatter().format(record("failed", (), exc_info=sys.exc_info()))
    log_record = json.loads(line)["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    extra = log_record["attributes"][2:]
    attributes = {item["key"]: item["value"]["stringValue"] for item in extra}
    assert attributes["exception.type"] == "ValueError"
    assert attributes["exception.message"] == "boom"
    assert "Traceback" in attributes["exception.stacktrace"]


def test_query_results_from_records_and_from_columns():
    records = QueryResult.from_records([{"a": 1}, {"a": 2, "b": 3}])
    assert records.columns == ("a", "b")
    columns = QueryResult.from_columns(["x", "y"], [[1, 2], [3, 4]])
    assert columns.rows == ({"x": 1, "y": 2}, {"x": 3, "y": 4})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("otlp", "otlp"),
        ("OtlpIndented", "otlp"),
        ("JSON", "json"),
        ("jsonindented", "json"),
        ("Text", "text"),
        ("syslog", "text"),
        (None, "text"),
    ],
)
def test_log_formats_use_the_powershell_modules_names(value, expected):
    assert normalise_format(value) == expected


@pytest.mark.parametrize(
    ("verbosity", "name", "expected"),
    [
        (0, None, logging.WARNING),
        (0, "TRACE", logging.DEBUG),
        (0, "Info", logging.INFO),
        (0, "SUCCESS", logging.INFO),
        (0, "warn", logging.WARNING),
        (0, "FATAL", logging.CRITICAL),
        (0, "loud", logging.WARNING),
        (1, "ERROR", logging.INFO),
        (2, "ERROR", logging.DEBUG),
    ],
)
def test_log_levels_use_the_powershell_modules_names_and_v_wins(verbosity, name, expected):
    assert resolve_level(verbosity, name) == expected
