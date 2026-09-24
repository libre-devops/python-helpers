"""Read a list of names from arguments, stdin, a text file or a CSV column.

Commands that take devices, users or vaults accept them however they are to hand:
``"a,b,c"``, several arguments, ``-`` for stdin, or a file. A text file holds names
separated by commas, spaces or new lines, with ``#`` comments. A CSV file (a ``.csv``
suffix, or any file when a column is named) is read by header, so an export from a
spreadsheet or a portal works as it is.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import split_names


def read_names(
    values: Sequence[str] = (),
    *,
    stdin: TextIO | None = None,
    from_file: Path | None = None,
    column: str | None = None,
) -> list[str]:
    """Every name given, in order, with blanks and case-insensitive repeats dropped.

    ``-`` among ``values`` reads ``stdin`` in its place. ``column`` picks a CSV column
    (by header, case-insensitively) and applies to ``from_file``, or to stdin when there
    is no file.
    """
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
        try:
            text = from_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise InputError(f"cannot read {from_file}: {exc}") from None
        if column or from_file.suffix.lower() == ".csv":
            collected.extend(_from_csv(text, column, str(from_file)))
        else:
            collected.extend(_from_text(text))
    return _dedupe(collected)


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
    reader = csv.DictReader(io.StringIO(text))
    headers = [header.strip() for header in reader.fieldnames or []]
    if not headers:
        raise InputError(f"{source} has no CSV header row")
    wanted = column.strip().casefold() if column else None
    if wanted is None:
        if len(headers) != 1:
            raise InputError(
                f"{source} has several columns",
                hint=f"pick one with --column ({', '.join(headers)})",
            )
        wanted = headers[0].casefold()
    match = next((raw for raw in reader.fieldnames or [] if raw.strip().casefold() == wanted), None)
    if match is None:
        raise InputError(
            f"{source} has no column {column!r}", hint=f"columns: {', '.join(headers)}"
        )
    # Cells are kept whole, so a CSV column may hold names with spaces in them.
    return [(row.get(match) or "").strip() for row in reader if (row.get(match) or "").strip()]
