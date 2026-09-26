"""Logging setup for the CLI: human text, flat JSON, or the OpenTelemetry wire format.

Library modules only call ``logging.getLogger(__name__)``; they never configure
handlers. The CLI calls ``configure_logging`` once. Logs go to stderr so they never mix
with data written to stdout.

``otlp`` writes the OpenTelemetry file format: JSON Lines, each line a complete OTLP/JSON
``LogsData`` (the same object an ``ExportLogsServiceRequest`` is) holding one record, as
``Write-LdoLog`` does in LibreDevOpsHelpers. An OpenTelemetry Collector reads it with the
``otlp_json_file`` receiver, or, from a container's logs, with the ``file_log`` receiver
and the ``otlp_json`` connector, with no parsing rules either way. The two tools read the
same variables (``LDO_LOG_FORMAT``, ``LDO_LOG_LEVEL``, ``LDO_SERVICE_NAME`` and the trace
context), so one pipeline setting controls both. One difference is deliberate: with
nothing set, this CLI writes readable text.

https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/
https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from collections.abc import Mapping
from typing import Any, ClassVar
from urllib.parse import unquote

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand, colour

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


class BriefFormatter(logging.Formatter):
    """A record as the command's own messages read, ``warning: ...``, coloured when asked:
    how a library warning looks without -v, where the time and the logger are noise."""

    _COLOURS: ClassVar[dict[int, str]] = {
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "red",
    }

    def __init__(self, *, coloured: bool = False) -> None:
        super().__init__()
        self.coloured = coloured

    def format(self, record: logging.LogRecord) -> str:
        """``level: message``, and the traceback when there is one."""
        text = f"{record.levelname.lower()}: {record.getMessage()}"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        shade = self._COLOURS.get(record.levelno)
        return colour.style(text, shade) if self.coloured and shade else text


class JsonFormatter(logging.Formatter):
    """One flat JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        """One record as a JSON object: time, level, logger, message, and a hint or exception."""
        data: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        hint = getattr(record, "hint", None)  # render.error's extra={"hint": ...}
        if hint:
            data["hint"] = hint
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


class OtlpFormatter(logging.Formatter):
    """One OTLP/JSON ``LogsData`` per record, on one line.

    OTLP's JSON rules differ from plain proto3 JSON: 64-bit integers such as timestamps are
    strings, ``severityNumber`` is the integer, ``traceId`` and ``spanId`` are lowercase
    hex, and attribute values are typed. Attribute names follow the semantic conventions.

    The resource describes what is logging: ``service.name`` (``LDO_SERVICE_NAME``, else
    ``OTEL_SERVICE_NAME``, else the command), ``service.version`` and, with
    ``LDO_DEPLOYMENT_ENVIRONMENT``, ``deployment.environment.name``; anything else comes
    from ``OTEL_RESOURCE_ATTRIBUTES``. ``LDO_TRACE_ID``, ``LDO_SPAN_ID`` and
    ``LDO_CORRELATION_ID`` put every record in a trace, so a CI run's logs join up; an id
    that is not valid hex of the right width is left out rather than sent and rejected.
    """

    def __init__(
        self,
        service_name: str | None = None,
        service_version: str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ):
        super().__init__()
        env = os.environ if environ is None else environ
        self._resource = {"attributes": _resource_attributes(env, service_name, service_version)}
        correlation = (env.get(brand.env_var("CORRELATION_ID")) or "").strip()
        self._correlation_id = correlation
        self._trace_id = otlp_hex_id(env.get(brand.env_var("TRACE_ID")), 32) or otlp_hex_id(
            correlation, 32
        )
        self._span_id = otlp_hex_id(env.get(brand.env_var("SPAN_ID")), 16)

    def format(self, record: logging.LogRecord) -> str:
        """One record as an OTLP/JSON LogsData document, on one line."""
        nanos = str(int(record.created * 1_000_000_000))
        attributes = [
            _attribute("code.function.name", f"{record.name}.{record.funcName}"),
            _attribute("code.line.number", record.lineno),
        ]
        if self._correlation_id:
            attributes.append(_attribute("correlation_id", self._correlation_id))
        hint = getattr(record, "hint", None)
        if hint:
            attributes.append(_attribute("hint", str(hint)))
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
        log_record: dict[str, Any] = {
            "timeUnixNano": nanos,
            "observedTimeUnixNano": nanos,
            "severityNumber": _SEVERITY.get(record.levelno, 9),
            "severityText": record.levelname,
            "body": {"stringValue": record.getMessage()},
            "attributes": attributes,
        }
        if self._trace_id:
            log_record["traceId"] = self._trace_id
        if self._span_id:
            log_record["spanId"] = self._span_id
        request = {
            "resourceLogs": [
                {
                    "resource": self._resource,
                    "scopeLogs": [{"scope": {"name": record.name}, "logRecords": [log_record]}],
                }
            ]
        }
        return json.dumps(request, separators=(",", ":"))


def otlp_hex_id(value: str | None, length: int) -> str:
    """A trace (32) or span (16) id in OTLP's lowercase hex, or "" when ``value`` is not one.

    Dashes are dropped, so a GUID, which is 16 bytes, becomes a trace id: a CI run's id
    can join its logs up without reformatting. An all-zero id is invalid in W3C trace
    context, so it is refused too. Refusing means leaving the field out: a collector
    rejects a whole payload with a bad id, and logging must never lose the record.
    """
    candidate = (value or "").strip().replace("-", "").lower()
    if len(candidate) != length or candidate.strip("0123456789abcdef") or not candidate.strip("0"):
        return ""
    return candidate


def _resource_attributes(
    environ: Mapping[str, str], service_name: str | None, service_version: str | None
) -> list[dict[str, Any]]:
    extra = _parse_resource_attributes(environ.get("OTEL_RESOURCE_ATTRIBUTES", ""))
    named = extra.pop("service.name", None)
    versioned = extra.pop("service.version", None)
    placed = extra.pop("deployment.environment.name", None)
    name = (
        service_name
        or environ.get(brand.env_var("SERVICE_NAME"))
        or environ.get("OTEL_SERVICE_NAME")
        or named
        or SERVICE_NAME
    )
    version = service_version or environ.get(brand.env_var("SERVICE_VERSION")) or versioned
    environment = environ.get(brand.env_var("DEPLOYMENT_ENVIRONMENT")) or placed
    attributes = [
        _attribute("service.name", name),
        _attribute("service.version", version or __version__),
    ]
    if environment:
        attributes.append(_attribute("deployment.environment.name", environment))
    attributes.extend(_attribute(key, value) for key, value in extra.items())
    return attributes


def _parse_resource_attributes(text: str) -> dict[str, str]:
    """``OTEL_RESOURCE_ATTRIBUTES``: ``key=value`` pairs, comma separated, values
    percent-encoded. A malformed pair is skipped, as the specification allows."""
    found: dict[str, str] = {}
    for pair in text.split(","):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            found[unquote(key.strip())] = unquote(value.strip())
    return found


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
    elif verbosity:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
    else:
        handler.setFormatter(BriefFormatter(coloured=colour.wanted(sys.stderr)))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # urllib3 logs each connection at DEBUG; that is noise unless asked for twice over.
    logging.getLogger("urllib3").setLevel(logging.DEBUG if verbosity >= 3 else logging.WARNING)
