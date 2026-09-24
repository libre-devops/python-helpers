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


def note(text: str) -> None:
    """A dim informational line on stderr."""
    typer.secho(text, fg="bright_black", err=True)


def warn(text: str) -> None:
    typer.secho(f"warning: {text}", fg="yellow", err=True)


def banner(*, force: bool = False) -> None:
    """The brand's welcome banner, on stderr so it never mixes with data.

    Shown only on a terminal, and never when the brand's ``NO_BANNER`` variable is set,
    unless ``force`` (someone asked for it). ``NO_COLOR`` keeps it, without colour.
    """
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
    """JSON on stdout, for piping into jq or another script."""
    typer.echo(json.dumps(data, indent=2, default=_json_default))


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
    return f"{value.astimezone():%Y-%m-%d %H:%M} ({relative})"


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
