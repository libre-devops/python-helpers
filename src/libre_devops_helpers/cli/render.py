"""Output. Data goes to stdout; notes and warnings go to stderr.

Every data command offers four shapes through ``-o``: an aligned table for people, JSON
(the services' full records) for jq and scripts, CSV for spreadsheets and TSV for shell
pipelines. ``--sort`` and ``--unique`` arrange the rows of the table, CSV and TSV first.
Tables are aligned with ``str.ljust`` and coloured after padding, so colour codes never
upset the alignment. Colour is decided in ``core.colour``; click strips it when the
output is not a terminal, so piped output stays plain.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import typer

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand, colour, sorting
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.tokens import Check

# A cell is plain text, or (text, colour) where colour is a typer/click colour name.
Cell = str | tuple[str, str | None]


class Output(StrEnum):
    """The shapes a data command can write."""

    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    TSV = "tsv"


_CHECK_COLOURS = {"pass": "green", "warn": "yellow", "fail": "red"}


def echo(text: str = "", *, err: bool = False) -> None:
    """Write ``text`` and a line break to stdout, or with ``err`` to stderr."""
    typer.echo(text, err=err)


_log = logging.getLogger(__name__)


class _Mode:
    """Set for each run: whether the log format is structured (json or otlp), and how
    ``--sort`` and ``--unique`` arrange rows: (column, descending) pairs, and columns."""

    structured = False
    order: tuple[tuple[str, bool], ...] = ()
    distinct: tuple[str, ...] = ()


def sort_rows(specs: Sequence[str] | None) -> None:
    """Rows from here on are sorted by ``specs``: ``COLUMN`` or ``COLUMN:desc``, most
    significant first (``--sort``). None or empty leaves them in the order they came."""
    try:
        _Mode.order = tuple(sorting.parse_sort(spec) for spec in specs or ())
    except LdoError as exc:
        raise typer.BadParameter(f"{exc}; {exc.hint}") from None


def unique_rows(columns: Sequence[str] | None) -> None:
    """Rows from here on, once sorted, are kept only the first time their ``columns`` hold
    what they hold (``--unique``). None or empty keeps every row."""
    _Mode.distinct = tuple(columns or ())


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
    """A warning on stderr (a WARNING record in a structured log format)."""
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
    plain = colour.setting() is False
    # Diagonal rainbow bands, which follow the unicorn's slant; any brand's art gets them.
    for row, line in enumerate(brand.BANNER.strip("\n").splitlines()):
        typer.echo(line if plain else colour.diagonal(line, row), err=True)
    typer.secho(f"{brand.DISPLAY_NAME}  {brand.COMMAND} {__version__}", dim=True, err=True)
    typer.echo(err=True)


def title(text: str) -> str:
    """``text`` in bold, for a heading."""
    return colour.style(text, bold=True)


def print_json(data: Any) -> None:
    """JSON on stdout: coloured on a terminal, plain when piped into jq or a script."""
    if colour.wanted():
        typer.echo(colour.json_text(_plain(data)), color=True)
    else:
        typer.echo(json.dumps(data, indent=2, default=_json_default))


def _plain(data: Any) -> Any:
    """``data`` as plain JSON values: datetimes, mappings and the rest turned as for -o json."""
    return json.loads(json.dumps(data, default=_json_default))


def emit(
    output: Output,
    headers: Sequence[str],
    rows: Iterable[Sequence[Cell]],
    records: Any,
) -> None:
    """Write data in the chosen shape: ``rows`` for a table, CSV or TSV, ``records`` for JSON.

    The rows are sorted and made unique first, as ``--sort`` and ``--unique`` asked.
    """
    if output is Output.JSON:
        _json_is_not_arranged()
        print_json(records)
        return
    rows = arranged(headers, rows)
    if output is Output.CSV:
        typer.echo(csv_text(headers, rows), nl=False)
    elif output is Output.TSV:
        typer.echo(tsv_text(rows), nl=False)
    else:
        typer.echo(table(headers, rows))


def arranged(headers: Sequence[str], rows: Iterable[Sequence[Cell]]) -> Iterable[Sequence[Cell]]:
    """``rows`` sorted by the ``--sort`` columns, then one for each ``--unique`` value."""
    if not _Mode.order and not _Mode.distinct:
        return rows
    order = [(sorting.column_index(headers, name), down) for name, down in _Mode.order]
    distinct = [sorting.column_index(headers, name) for name in _Mode.distinct]
    listed = sorting.sort_records(
        rows, *((lambda row, at=at: _text(row[at]), down) for at, down in order)
    )
    if distinct:
        listed = sorting.unique(listed, lambda row: tuple(_text(row[at]) for at in distinct))
    return listed


def _text(value: Cell) -> str:
    return value[0] if isinstance(value, tuple) else value


def _json_is_not_arranged() -> None:
    if _Mode.order or _Mode.distinct:
        warn("--sort and --unique arrange table, CSV and TSV rows; for JSON use jq's sort_by")


def csv_text(headers: Sequence[str], rows: Iterable[Sequence[Cell]]) -> str:
    """CSV with a header row, and colours dropped."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([value[0] if isinstance(value, tuple) else value for value in row])
    return buffer.getvalue()


def tsv_text(rows: Iterable[Sequence[Cell]]) -> str:
    """Tab-separated values, one row a line, with no header: the Azure CLI's ``-o tsv``,
    for shell pipelines (``cut -f1``, ``while read``). A tab or line break inside a value
    becomes a space, so a row is always one line."""
    lines = []
    for row in rows:
        cells = (value[0] if isinstance(value, tuple) else value for value in row)
        lines.append("\t".join(_TSV_UNSAFE.sub(" ", str(cell)) for cell in cells))
    return "".join(line + "\n" for line in lines)


_TSV_UNSAFE = re.compile(r"[\t\r\n]+")


def query_result(result: QueryResult, output: Output) -> None:
    """A query result from Advanced Hunting, Resource Graph or Log Analytics."""
    if output is Output.JSON:
        _json_is_not_arranged()
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


def table(
    headers: Sequence[str], rows: Iterable[Sequence[Cell]], *, width: int | None = None
) -> str:
    """Left-aligned columns separated by two spaces, with a rule under the header.

    On a terminal the last column (a detail or description, usually) is cut to fit the
    window, with an ellipsis, so a long message never wraps across the table. ``width``
    sets the window; piped or redirected, nothing is cut.
    """
    body = [[_cell(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in body:
        for index, (text, _) in enumerate(row):
            widths[index] = max(widths[index], len(text))
    if width is None and sys.stdout.isatty():
        width = shutil.get_terminal_size().columns
    if width and widths and sum(widths) + 2 * (len(widths) - 1) > width:
        room = width - sum(widths[:-1]) - 2 * (len(widths) - 1)
        if room >= 20:
            widths[-1] = room
            body = [[*row[:-1], _clip(row[-1], room)] for row in body]
    lines = [
        _line([(header, None) for header in headers], widths, bold=True),
        _line([("-" * width, None) for width in widths], widths),
    ]
    lines.extend(_line(row, widths) for row in body)
    return "\n".join(lines)


def _clip(cell: tuple[str, str | None], room: int) -> tuple[str, str | None]:
    text, fg = cell
    return (text if len(text) <= room else text[: room - 1] + "…", fg)


def pairs(items: Iterable[tuple[str, str]]) -> str:
    """Aligned ``label  value`` lines; empty values show as ``-``."""
    materialised = list(items)
    width = max((len(label) for label, _ in materialised), default=0)
    return "\n".join(
        f"{colour.style(label.ljust(width), bold=True)}  {value or '-'}"
        for label, value in materialised
    )


def checks_table(checks: Iterable[Check]) -> str:
    """A token's checks as a table: each one's result, name and detail."""
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


def moment(value: datetime | None) -> str:
    """Local time to the second, for events in order: ``2026-09-24 14:05:31``. In UTC,
    and says so, where this platform cannot convert it (before 1970, on Windows)."""
    if value is None:
        return "-"
    try:
        return f"{value.astimezone():%Y-%m-%d %H:%M:%S}"
    except (OverflowError, OSError, ValueError):
        return f"{value:%Y-%m-%d %H:%M:%S} UTC"


def yes_no(value: bool | None) -> str:
    """``yes``, ``no``, or ``-`` when it is not known."""
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
    for index, ((text, fg), width) in enumerate(zip(cells, widths, strict=True)):
        padded = text if index == last else text.ljust(width)
        parts.append(colour.style(padded, fg, bold=bold))
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
