"""Logging setup for the CLI: human text, flat JSON, or the OpenTelemetry wire format.

Library modules only call ``logging.getLogger(__name__)``; they never configure
handlers. The CLI calls ``configure_logging`` once. Logs go to stderr so they never mix
with data written to stdout.

``otlp`` writes one complete OTLP/JSON ``ExportLogsServiceRequest`` per line, the same
shape ``Write-LdoLog`` emits in LibreDevOpsHelpers, so a collector's ``otlpjsonfile``
receiver reads either tool's logs without any parsing rules. The two tools also read the
same ``LDO_LOG_FORMAT`` and ``LDO_LOG_LEVEL`` variables, so one pipeline setting controls
both. One difference is deliberate: with nothing set, this CLI writes readable text.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand

LOG_FORMATS = ("text", "json", "otlp")

# LibreDevOpsHelpers' names for formats and levels, so its settings mean the same here.
_FORMAT_ALIASES = {"jsonindented": "json", "otlpindented": "otlp"}
_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "success": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}
SERVICE_NAME = brand.COMMAND

# https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber
_SEVERITY = {
    logging.DEBUG: 5,
    logging.INFO: 9,
    logging.WARNING: 13,
    logging.ERROR: 17,
    logging.CRITICAL: 21,
}


class JsonFormatter(logging.Formatter):
    """One flat JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


class OtlpFormatter(logging.Formatter):
    """One OTLP/JSON ``ExportLogsServiceRequest`` per record.

    OTLP's JSON rules differ from plain proto3 JSON: 64-bit integers such as timestamps
    are strings, ``severityNumber`` is the integer, and attribute values are typed.
    """

    def __init__(self, service_name: str = SERVICE_NAME, service_version: str = __version__):
        super().__init__()
        self._resource = {
            "attributes": [
                _attribute("service.name", service_name),
                _attribute("service.version", service_version),
            ]
        }

    def format(self, record: logging.LogRecord) -> str:
        nanos = str(int(record.created * 1_000_000_000))
        attributes = [
            _attribute("code.function", record.funcName),
            _attribute("code.lineno", record.lineno),
        ]
        if record.exc_info and record.exc_info[0] is not None:
            error_type, error, trace = record.exc_info
            attributes += [
                _attribute("exception.type", error_type.__name__),
                _attribute("exception.message", str(error)),
                _attribute(
                    "exception.stacktrace",
                    "".join(traceback.format_exception(error_type, error, trace)),
                ),
            ]
        log_record = {
            "timeUnixNano": nanos,
            "observedTimeUnixNano": nanos,
            "severityNumber": _SEVERITY.get(record.levelno, 9),
            "severityText": record.levelname,
            "body": {"stringValue": record.getMessage()},
            "attributes": attributes,
        }
        request = {
            "resourceLogs": [
                {
                    "resource": self._resource,
                    "scopeLogs": [{"scope": {"name": record.name}, "logRecords": [log_record]}],
                }
            ]
        }
        return json.dumps(request, separators=(",", ":"))


def _attribute(key: str, value: str | int) -> dict[str, Any]:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def normalise_format(fmt: str | None) -> str:
    """``text``, ``json`` or ``otlp`` for any spelling LibreDevOpsHelpers accepts."""
    value = (fmt or "text").strip().lower()
    value = _FORMAT_ALIASES.get(value, value)
    return value if value in LOG_FORMATS else "text"


def resolve_level(verbosity: int = 0, level_name: str | None = None) -> int:
    """-v (info) and -vv (debug) win; otherwise ``level_name`` if valid; otherwise warnings."""
    if verbosity == 1:
        return logging.INFO
    if verbosity >= 2:
        return logging.DEBUG
    return _LEVELS.get((level_name or "").strip().lower(), logging.WARNING)


def configure_logging(
    verbosity: int = 0, fmt: str | None = "text", level_name: str | None = None
) -> None:
    """Send logs to stderr at the resolved level, in the chosen format.

    An unknown format or level falls back to the default, because a logging preference
    must never stop the command it is logging about.
    """
    level = resolve_level(verbosity, level_name)
    fmt = normalise_format(fmt)
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    elif fmt == "otlp":
        handler.setFormatter(OtlpFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # urllib3 logs each connection at DEBUG; that is noise unless asked for twice over.
    logging.getLogger("urllib3").setLevel(logging.DEBUG if verbosity >= 3 else logging.WARNING)
