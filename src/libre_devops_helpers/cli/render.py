"""Output. Data goes to stdout; notes and warnings go to stderr.

Every data command offers three shapes through ``-o``: an aligned table for people, JSON
(the services' full records) for jq and scripts, and CSV for spreadsheets. Tables are
aligned with ``str.ljust`` and coloured with ``typer.style`` after padding, so colour
codes never upset the alignment. Click strips colour when the output is not a
terminal, so piped output stays plain.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import typer

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.tokens import Check

# A cell is plain text, or (text, colour) where colour is a typer/click colour name.
Cell = str | tuple[str, str | None]

# The banner's colours (256-colour codes, red through to pink), laid in diagonal bands that
# follow the unicorn's slant. Any brand's art gets the same sweep.
_RAINBOW = (196, 208, 226, 46, 51, 33, 129, 201)
_BAND = 6


class Output(StrEnum):
    """The shapes a data command can write."""

    TABLE = "table"
    JSON = "json"
    CSV = "csv"


_CHECK_COLOURS = {"pass": "green", "warn": "yellow", "fail": "red"}


def echo(text: str = "", *, err: bool = False) -> None:
    typer.echo(text, err=err)


_log = logging.getLogger(__name__)


class _Mode:
    """Whether the log format is structured (json or otlp): set once, by the app."""

    structured = False


def structured_output(enabled: bool) -> None:
    """With a json or otlp log format, stderr carries log records only, so it is clean
    JSON Lines for a collector: notes, warnings and errors become records too."""
    _Mode.structured = enabled


def note(text: str) -> None:
    """A dim informational line on stderr (an INFO record in a structured log format)."""
    if _Mode.structured:
        _log.info(text)
        return
    typer.secho(text, fg="bright_black", err=True)


def warn(text: str) -> None:
    if _Mode.structured:
        _log.warning(text)
        return
    typer.secho(f"warning: {text}", fg="yellow", err=True)


def error(text: str, hint: str | None = None) -> None:
    """An error, and what to do about it, on stderr (an ERROR record, hint attached)."""
    if _Mode.structured:
        _log.error(text, extra={"hint": hint} if hint else None)
        return
    typer.secho(f"error: {text}", fg="red", err=True)
    if hint:
        typer.secho(f"hint: {hint}", fg="yellow", err=True)


def notify(text: str) -> None:
    """Something the person must see now, such as a sign-in code: never filtered out."""
    if _Mode.structured:
        _log.warning(text)
        return
    typer.secho(text, fg="cyan", err=True)


def checks_to_stderr(checks: Iterable[Check]) -> None:
    """A token's checks on stderr: the table, or one record each in a structured format."""
    if not _Mode.structured:
        echo(checks_table(checks), err=True)
        return
    levels = {"fail": logging.ERROR, "warn": logging.WARNING}
    for check in checks:
        _log.log(levels.get(check.status, logging.INFO), f"{check.name}: {check.detail}")


def banner(*, force: bool = False) -> None:
    """The brand's welcome banner, on stderr so it never mixes with data.

    Shown only on a terminal, and never when the brand's ``NO_BANNER`` variable is set,
    unless ``force`` (someone asked for it). ``NO_COLOR`` keeps it, without colour.
    """
    if _Mode.structured and not force:
        return
    if not force and (not sys.stderr.isatty() or os.environ.get(brand.env_var("NO_BANNER"))):
        return
    plain = bool(os.environ.get("NO_COLOR"))
    for row, line in enumerate(brand.BANNER.strip("\n").splitlines()):
        typer.echo(line if plain else _diagonal(line, row), err=True)
    typer.secho(f"{brand.DISPLAY_NAME}  {brand.COMMAND} {__version__}", dim=True, err=True)
    typer.echo(err=True)


def _diagonal(line: str, row: int) -> str:
    """Colour ``line`` in bands that run along the diagonal, one style call per run."""
    parts: list[str] = []
    run: list[str] = []
    colour: int | None = None
    for col, char in enumerate(line):
        band = _RAINBOW[((col + 2 * row) // _BAND) % len(_RAINBOW)]
        if band != colour and run:
            parts.append(typer.style("".join(run), fg=colour, bold=True))
            run = []
        colour = band
        run.append(char)
    if run:
        parts.append(typer.style("".join(run), fg=colour, bold=True))
    return "".join(parts)


def title(text: str) -> str:
    return typer.style(text, bold=True)


def print_json(data: Any) -> None:
    """JSON on stdout: coloured on a terminal, plain when piped into jq or a script."""
    if colour_wanted():
        typer.echo(colour_json(_plain(data)), color=True)
    else:
        typer.echo(json.dumps(data, indent=2, default=_json_default))


def colour_wanted(stream: Any = None) -> bool:
    """Whether ``stream`` (stdout by default) is a terminal that wants colour."""
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")


# JSON's colours (256-colour codes): brackets take the banner's rainbow by nesting depth.
_JSON_KEY = 75
_JSON_STRING = 114
_JSON_NUMBER = 215
_JSON_BOOL = 176
_JSON_NULL = 244


def colour_json(
    data: Any, *, indent: int | None = 2, sort_keys: bool = False, ensure_ascii: bool = False
) -> str:
    """``data`` as JSON laid out as ``json.dumps`` would, in colour.

    Keys, strings, numbers, booleans and null each have a colour, and brackets are
    coloured by how deeply they nest, in the banner's rainbow, so matching pairs share
    one. Strip the colour and the text is exactly ``json.dumps(data, indent=indent)``.
    """

    def paint(text: str, colour: int, *, bold: bool = False) -> str:
        return typer.style(text, fg=colour, bold=bold)

    def bracket(char: str, depth: int) -> str:
        return paint(char, _RAINBOW[depth % len(_RAINBOW)], bold=True)

    def scalar(value: Any) -> str:
        text = json.dumps(value, ensure_ascii=ensure_ascii)
        if value is None:
            return paint(text, _JSON_NULL)
        if isinstance(value, bool):
            return paint(text, _JSON_BOOL)
        if isinstance(value, int | float):
            return paint(text, _JSON_NUMBER)
        return paint(text, _JSON_STRING)

    def render(value: Any, depth: int) -> str:
        if isinstance(value, dict):
            items = sorted(value.items()) if sort_keys else list(value.items())
            if not items:
                return bracket("{", depth) + bracket("}", depth)
            parts = [
                paint(json.dumps(str(key), ensure_ascii=ensure_ascii), _JSON_KEY, bold=True)
                + (": " if indent is not None else ":")
                + render(item, depth + 1)
                for key, item in items
            ]
            return bracket("{", depth) + join(parts, depth) + bracket("}", depth)
        if isinstance(value, list):
            if not value:
                return bracket("[", depth) + bracket("]", depth)
            parts = [render(item, depth + 1) for item in value]
            return bracket("[", depth) + join(parts, depth) + bracket("]", depth)
        return scalar(value)

    def join(parts: list[str], depth: int) -> str:
        if indent is None:
            return ",".join(parts)
        inner = "\n" + " " * (indent * (depth + 1))
        return inner + ("," + inner).join(parts) + "\n" + " " * (indent * depth)

    return render(data, 0)


def _plain(data: Any) -> Any:
    """``data`` as plain JSON values: datetimes, mappings and the rest turned as for -o json."""
    return json.loads(json.dumps(data, default=_json_default))


def emit(
    output: Output,
    headers: Sequence[str],
    rows: Iterable[Sequence[Cell]],
    records: Any,
) -> None:
    """Write data in the chosen shape: ``rows`` for a table or CSV, ``records`` for JSON."""
    if output is Output.JSON:
        print_json(records)
    elif output is Output.CSV:
        typer.echo(csv_text(headers, rows), nl=False)
    else:
        typer.echo(table(headers, rows))


def csv_text(headers: Sequence[str], rows: Iterable[Sequence[Cell]]) -> str:
    """CSV with a header row, and colours dropped."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([value[0] if isinstance(value, tuple) else value for value in row])
    return buffer.getvalue()


def query_result(result: QueryResult, output: Output) -> None:
    """A query result from Advanced Hunting, Resource Graph or Log Analytics."""
    if output is Output.JSON:
        print_json(list(result.rows))
    else:
        emit(
            output,
            result.columns,
            ([_query_cell(row.get(column)) for column in result.columns] for row in result.rows),
            None,
        )
    for warning in result.warnings:
        warn(warning)
    if result.truncated:
        warn(f"stopped after {len(result.rows)} rows; raise --limit to fetch more")


def table(headers: Sequence[str], rows: Iterable[Sequence[Cell]]) -> str:
    """Left-aligned columns separated by two spaces, with a rule under the header."""
    body = [[_cell(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in body:
        for index, (text, _) in enumerate(row):
            widths[index] = max(widths[index], len(text))
    lines = [
        _line([(header, None) for header in headers], widths, bold=True),
        _line([("-" * width, None) for width in widths], widths),
    ]
    lines.extend(_line(row, widths) for row in body)
    return "\n".join(lines)


def pairs(items: Iterable[tuple[str, str]]) -> str:
    """Aligned ``label  value`` lines; empty values show as ``-``."""
    materialised = list(items)
    width = max((len(label) for label, _ in materialised), default=0)
    return "\n".join(
        f"{typer.style(label.ljust(width), bold=True)}  {value or '-'}"
        for label, value in materialised
    )


def checks_table(checks: Iterable[Check]) -> str:
    return table(
        ["RESULT", "CHECK", "DETAIL"],
        [
            [(check.status.upper(), _CHECK_COLOURS[check.status]), check.name, check.detail]
            for check in checks
        ],
    )


def when(value: datetime | None, *, now: datetime | None = None) -> str:
    """Local time plus a relative age: ``2026-09-24 14:05 (3h 02m ago)``."""
    if value is None:
        return "-"
    now = now or datetime.now(UTC)
    if value > now:
        relative = f"in {format_duration(value - now)}"
    else:
        relative = f"{format_duration(now - value)} ago"
    try:
        local = value.astimezone()
    except (OverflowError, OSError, ValueError):
        # Outside what this platform's clock converts (before 1970, on Windows): say UTC.
        return f"{value:%Y-%m-%d %H:%M} UTC ({relative})"
    return f"{local:%Y-%m-%d %H:%M} ({relative})"


def yes_no(value: bool | None) -> str:
    return "-" if value is None else "yes" if value else "no"


def _cell(value: Cell) -> tuple[str, str | None]:
    if isinstance(value, tuple):
        return (value[0] or "-", value[1])
    return (value or "-", None)


def _line(
    cells: Sequence[tuple[str, str | None]], widths: Sequence[int], bold: bool = False
) -> str:
    parts = []
    last = len(cells) - 1
    for index, ((text, colour), width) in enumerate(zip(cells, widths, strict=True)):
        padded = text if index == last else text.ljust(width)
        parts.append(typer.style(padded, fg=colour, bold=bold) if colour or bold else padded)
    return "  ".join(parts)


def _query_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(value, default=_json_default)


def _json_default(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Check):
        return asdict(value)
    return str(value)
