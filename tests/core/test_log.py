import json
import logging

import pytest

from libre_devops_helpers.core.log import (
    JsonFormatter,
    OtlpFormatter,
    normalise_format,
    otlp_hex_id,
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


def test_otlp_is_one_logs_data_per_line_with_otlp_json_encoding():
    line = OtlpFormatter(service_version="9.9.9", environ={}).format(record())
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
    # The semantic conventions' current names, not the deprecated code.function/code.lineno.
    assert code["code.function.name"] == {"stringValue": "libre_devops_helpers.core.http._wait"}
    assert code["code.line.number"] == {"intValue": "42"}
    assert "traceId" not in log_record


def test_otlp_records_exceptions_as_semantic_attributes():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        line = OtlpFormatter(environ={}).format(record("failed", (), exc_info=sys.exc_info()))
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


def otlp(environ: dict[str, str], **options) -> dict:
    return json.loads(OtlpFormatter(environ=environ, **options).format(record()))


def resource_of(request: dict) -> dict:
    items = request["resourceLogs"][0]["resource"]["attributes"]
    return {item["key"]: item["value"]["stringValue"] for item in items}


def test_the_resource_takes_the_same_variables_as_write_ldolog_and_otel_ones():
    environ = {
        "LDO_SERVICE_NAME": "patch-ring-1",
        "LDO_SERVICE_VERSION": "2026.09",
        "LDO_DEPLOYMENT_ENVIRONMENT": "prod",
        "OTEL_SERVICE_NAME": "ignored, LDO_SERVICE_NAME wins",
        "OTEL_RESOURCE_ATTRIBUTES": "team=platform%20ops,service.name=also-ignored,bad,=x",
    }
    assert resource_of(otlp(environ)) == {
        "service.name": "patch-ring-1",
        "service.version": "2026.09",
        "deployment.environment.name": "prod",
        "team": "platform ops",
    }
    assert resource_of(otlp({"OTEL_SERVICE_NAME": "from-otel"}))["service.name"] == "from-otel"
    assert resource_of(otlp({}))["service.name"] == "ldo"


def test_a_trace_context_puts_every_record_in_one_trace():
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    log_record = otlp({"LDO_TRACE_ID": trace.upper(), "LDO_SPAN_ID": "00f067aa0ba902b7"})[
        "resourceLogs"
    ][0]["scopeLogs"][0]["logRecords"][0]
    assert (log_record["traceId"], log_record["spanId"]) == (trace, "00f067aa0ba902b7")


def test_a_correlation_id_is_kept_and_seeds_the_trace_when_it_is_a_guid():
    run_id = "0b1c2d3e-aaaa-4bbb-8ccc-123456789abc"
    log_record = otlp({"LDO_CORRELATION_ID": run_id})["resourceLogs"][0]["scopeLogs"][0][
        "logRecords"
    ][0]
    assert log_record["traceId"] == run_id.replace("-", "")
    attributes = {item["key"]: item["value"] for item in log_record["attributes"]}
    assert attributes["correlation_id"] == {"stringValue": run_id}
    loose = otlp({"LDO_CORRELATION_ID": "build 42"})["resourceLogs"][0]["scopeLogs"][0]
    assert "traceId" not in loose["logRecords"][0]


@pytest.mark.parametrize(
    ("value", "length", "expected"),
    [
        ("0B1C2D3E-AAAA-4BBB-8CCC-123456789ABC", 32, "0b1c2d3eaaaa4bbb8ccc123456789abc"),
        ("0" * 32, 32, ""),  # all zeros is invalid
        ("4bf92f3577b34da6a3ce929d0e0e473", 32, ""),  # too short
        ("zz00f067aa0ba902", 16, ""),  # not hex
        (None, 16, ""),
        (" 00f067aa0ba902b7 ", 16, "00f067aa0ba902b7"),
    ],
)
def test_ids_are_normalised_or_refused(value, length, expected):
    assert otlp_hex_id(value, length) == expected
