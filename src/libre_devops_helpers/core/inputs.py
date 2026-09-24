"""Read a list of names from arguments, stdin, a text file, a CSV or an Excel workbook.

Commands that take devices, users or vaults accept them however they are to hand:
``"a,b,c"``, several arguments, ``-`` for stdin, or a file. A text file holds names
separated by commas, spaces or new lines, with ``#`` comments. A CSV file (a ``.csv``
suffix, or any file when a column is named) and an Excel workbook (``.xlsx``, ``.xlsm``,
``.xltx``, ``.xltm``) are read by column header, so a plan, an export from a portal or a
spreadsheet someone emailed works as it is, title rows above the header and all.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable, Sequence
from itertools import islice
from pathlib import Path
from typing import TextIO

from libre_devops_helpers.core import sheets
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import split_names

log = logging.getLogger(__name__)

# With a column named, the header is the first of this many non-blank rows to have it.
HEADER_SEARCH_ROWS = 25

# Cells of one row, and whether the row is hidden (in Excel; a CSV row never is).
Row = tuple[Sequence[str], bool]


def read_names(
    values: Sequence[str] = (),
    *,
    stdin: TextIO | None = None,
    from_file: Path | None = None,
    column: str | None = None,
    sheet: str | None = None,
) -> list[str]:
    """Every name given, in order, with blanks and case-insensitive repeats dropped.

    ``-`` among ``values`` reads ``stdin`` in its place. ``column`` picks a column (by
    header, case-insensitively) of a CSV or workbook ``from_file``, or of CSV on stdin
    when there is no file. ``sheet`` picks a workbook's sheet by tab name; without it,
    the one visible sheet with that column is used, or the first visible sheet when no
    column is named.
    """
    if sheet is not None and (from_file is None or not sheets.is_workbook(from_file)):
        raise InputError("--sheet applies to an Excel workbook only")
    collected: list[str] = []
    for value in values:
        if value == "-":
            if stdin is None:
                raise InputError("'-' reads names from stdin, but there is no stdin")
            text = stdin.read()
            collected.extend(_from_csv(text, column, "stdin") if column else _from_text(text))
        else:
            collected.extend(split_names([value]))
    if from_file is not None:
        collected.extend(_from_file(from_file, column, sheet))
    return _dedupe(collected)


def _from_file(path: Path, column: str | None, sheet: str | None) -> list[str]:
    sheets.check_readable(path)
    if sheets.is_workbook(path):
        return _from_workbook(path, column, sheet)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise InputError(
            f"{path} is not a text file", hint="use a text file, a CSV or an Excel workbook"
        ) from None
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from None
    if column or path.suffix.lower() == ".csv":
        return _from_csv(text, column, str(path))
    return _from_text(text)


def _from_text(text: str) -> list[str]:
    return split_names(line.split("#", 1)[0] for line in text.splitlines())


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for name in names:
        if name.casefold() not in seen:
            seen.add(name.casefold())
            kept.append(name)
    return kept


def _from_csv(text: str, column: str | None, source: str) -> list[str]:
    return _column(((cells, False) for cells in csv.reader(io.StringIO(text))), column, source)


def _from_workbook(path: Path, column: str | None, sheet: str | None) -> list[str]:
    with sheets.open_workbook(path) as book:
        chosen = book.sheet(sheet) if sheet is not None else _pick_sheet(book, column)
        return _column(book.rows(chosen), column, f"sheet {chosen.name!r} of {path}")


def _pick_sheet(book: sheets.Workbook, column: str | None) -> sheets.Sheet:
    """The one visible sheet with ``column`` in its header, or the first visible sheet."""
    visible = [sheet for sheet in book.sheets if not sheet.hidden]
    if not visible:
        raise InputError(
            f"{book.path} has only hidden sheets",
            hint=f"name one with --sheet ({', '.join(s.name for s in book.sheets)})",
        )
    if column is None:
        return visible[0]
    having = [sheet for sheet in visible if _has_column(book.rows(sheet), column)]
    if len(having) == 1:
        return having[0]
    names = ", ".join(sheet.name for sheet in having or visible)
    if having:
        raise InputError(
            f"several sheets of {book.path} have a column {column!r}",
            hint=f"pick one with --sheet ({names})",
        )
    raise InputError(
        f"no sheet of {book.path} has a column {column!r}",
        hint=f"check the header, or pick a sheet with --sheet ({names})",
    )


def _has_column(rows: Iterable[Row], column: str) -> bool:
    try:
        _header(iter(rows), column, "")
    except InputError:
        return False
    return True


def _column(rows: Iterable[Row], column: str | None, source: str) -> list[str]:
    """The non-blank values under the header ``column``, or under the only header."""
    remaining = iter(rows)
    index = _header(remaining, column, source)
    values: list[str] = []
    hidden = 0
    for cells, row_hidden in remaining:
        # Cells are kept whole, so a column may hold names with spaces in them.
        value = cells[index].strip() if index < len(cells) else ""
        if value:
            values.append(value)
            hidden += row_hidden
    if hidden:
        log.warning(
            "%d of the names in %s are in rows hidden or filtered out in Excel; they are included",
            hidden,
            source,
        )
    return values


def _header(rows: Iterable[Row], column: str | None, source: str) -> int:
    """Find the header row, consuming rows up to it, and return the column's index.

    Without ``column``, the header is the first non-blank row, and it must name one
    column only. With it, the header is the first of the first few non-blank rows to
    have that column, so title rows above the header do no harm.
    """
    wanted = column.strip().casefold() if column else None
    first: list[str] | None = None
    for row, _ in islice(_non_blank(rows), HEADER_SEARCH_ROWS):
        cells = [cell.strip() for cell in row]
        first = first or cells
        if wanted is None:
            named = [index for index, cell in enumerate(cells) if cell]
            if len(named) == 1:
                return named[0]
            raise InputError(
                f"{source} has several columns",
                hint=f"pick one with --column ({', '.join(cell for cell in cells if cell)})",
            )
        for index, cell in enumerate(cells):
            if cell.casefold() == wanted:
                return index
    if first is None:
        raise InputError(f"{source} has no header row")
    raise InputError(
        f"{source} has no column {column!r}",
        hint=f"columns: {', '.join(cell for cell in first if cell)}",
    )


def _non_blank(rows: Iterable[Row]) -> Iterable[Row]:
    return (row for row in rows if any(cell.strip() for cell in row[0]))
