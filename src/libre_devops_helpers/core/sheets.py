"""Read the cells of an Excel workbook (.xlsx, .xlsm, .xltx, .xltm), with the standard library.

An Office Open XML workbook is a zip of XML parts: the workbook lists its sheets,
relationship parts say which file holds each one, and most text lives once in a shared
strings table that cells point into. Only cell values are read. Formulas are never
evaluated (the value Excel saved with the file is used), and macros in an ``.xlsm`` are
never touched.

A workbook is untrusted input, so each part is streamed with a size cap (a zip can claim
any size, and a small file can inflate to gigabytes) and a document type declaration is
refused before the parser sees it, which rules out entity expansion attacks. Office never
writes one. Parts must be UTF-8, as Office writes them, so that check cannot be dodged by
declaring another encoding.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, NamedTuple
from xml.etree import ElementTree

from libre_devops_helpers.core.errors import InputError

SUFFIXES = frozenset({".xlsx", ".xlsm", ".xltx", ".xltm"})
# Spreadsheet formats this module cannot read, and what to do instead.
OTHER_FORMATS = {
    ".xls": "the old binary Excel format",
    ".xlsb": "the binary Excel format",
    ".ods": "an OpenDocument spreadsheet",
    ".numbers": "a Numbers spreadsheet",
}
SAVE_AS_HINT = "save it as .xlsx or .csv"
# Any one part may inflate to this much. A sheet of a million short rows fits.
MAX_PART_BYTES = 128 * 1024 * 1024
MAX_COLUMNS = 16_384  # Excel's own limit, column XFD
_CHUNK = 64 * 1024
# The first read is at least this long, so it holds the whole XML declaration.
_PROLOG = 1024
_DOCTYPE = b"<!DOCTYPE"
_UTF8_BOM = b"\xef\xbb\xbf"
_ENCODING = re.compile(rb"""^<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""")
# Legacy .xls files and password-protected workbooks are both OLE compound files.
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_CELL_COLUMN = re.compile(r"^([A-Za-z]{1,3})")


class SheetRow(NamedTuple):
    """The cell values of one row, left to right, and whether Excel hides the row.

    Rows are hidden by hand or by a filter; either way they are still in the file.
    """

    cells: list[str]
    hidden: bool


@dataclass(frozen=True)
class Sheet:
    """One worksheet: its tab name, whether the tab is hidden, and its part in the zip."""

    name: str
    hidden: bool
    part: str


class Workbook:
    """An open workbook. Use it as a context manager, or call :meth:`close`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._archive = _open_archive(path)
        try:
            self.sheets, strings_part = self._read_structure()
            self._strings = self._read_strings(strings_part) if strings_part else []
        except BaseException:
            self._archive.close()
            raise

    def __enter__(self) -> Workbook:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._archive.close()

    def sheet(self, name: str) -> Sheet:
        """The sheet with this tab name, matched case-insensitively. Hidden ones count."""
        wanted = name.strip().casefold()
        for sheet in self.sheets:
            if sheet.name.casefold() == wanted:
                return sheet
        raise InputError(
            f"{self.path} has no sheet {name!r}",
            hint=f"sheets: {', '.join(sheet.name for sheet in self.sheets)}",
        )

    def rows(self, sheet: Sheet) -> Iterator[SheetRow]:
        """Every row the sheet stores, in order. Empty rows Excel left out stay out."""
        for element in _elements(self._archive, sheet.part, self.path, "row"):
            yield SheetRow(self._row_cells(element), element.get("hidden") in {"1", "true"})
            element.clear()

    def _row_cells(self, row: ElementTree.Element) -> list[str]:
        values: dict[int, str] = {}
        position = -1
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            reference = _CELL_COLUMN.match(cell.get("r") or "")
            position = _column_index(reference.group(1)) if reference else position + 1
            if position < MAX_COLUMNS:
                values[position] = self._cell_value(cell)
        if not values:
            return []
        cells = [""] * (max(values) + 1)
        for index, value in values.items():
            cells[index] = value
        return cells

    def _cell_value(self, cell: ElementTree.Element) -> str:
        kind = cell.get("t", "n")
        if kind == "inlineStr":
            inline = _child(cell, "is")
            return _rich_text(inline) if inline is not None else ""
        value = _child(cell, "v")
        text = (value.text or "") if value is not None else ""
        if kind == "s":
            try:
                return self._strings[int(text)]
            except (ValueError, IndexError):
                raise InputError(
                    f"{self.path} is damaged: a cell points at a missing shared string"
                ) from None
        if kind == "b":
            return "TRUE" if text == "1" else "FALSE"
        if kind == "e":
            return ""  # #N/A, #REF! and the like hold no value worth reading
        return text

    def _read_structure(self) -> tuple[list[Sheet], str | None]:
        if "_rels/.rels" not in self._archive.namelist():
            raise InputError(f"{self.path} is not an Excel workbook", hint=SAVE_AS_HINT)
        workbook_part = _target(self._relationships("_rels/.rels", ""), "officeDocument")
        if workbook_part is None:
            raise InputError(f"{self.path} is not an Excel workbook", hint=SAVE_AS_HINT)
        folder = posixpath.dirname(workbook_part)
        rels_part = posixpath.join(folder, "_rels", posixpath.basename(workbook_part) + ".rels")
        relationships = self._relationships(rels_part, folder)
        sheets = []
        for element in _elements(self._archive, workbook_part, self.path, "sheet"):
            # The relationship id is r:id, in a namespace that differs between the
            # transitional and strict flavours of the format, so match it by local name.
            rel_id = next((v for k, v in element.attrib.items() if _local(k) == "id"), None)
            kind, part = relationships.get(rel_id or "", ("", ""))
            if kind == "worksheet":  # chart sheets and dialog sheets hold no cells
                hidden = element.get("state", "visible") != "visible"
                sheets.append(Sheet(element.get("name", ""), hidden, part))
        if not sheets:
            raise InputError(f"{self.path} has no worksheets")
        return sheets, _target(relationships, "sharedStrings")

    def _relationships(self, part: str, folder: str) -> dict[str, tuple[str, str]]:
        """Relationship id -> (type, part path), for the relationships part given."""
        found = {}
        for element in _elements(self._archive, part, self.path, "Relationship"):
            if element.get("TargetMode") == "External":
                continue
            target = element.get("Target", "")
            path = target[1:] if target.startswith("/") else posixpath.join(folder, target)
            kind = element.get("Type", "").rsplit("/", 1)[-1]
            found[element.get("Id", "")] = (kind, posixpath.normpath(path))
        return found

    def _read_strings(self, part: str) -> list[str]:
        strings = []
        for element in _elements(self._archive, part, self.path, "si"):
            strings.append(_rich_text(element))
            element.clear()
        return strings


def open_workbook(path: Path) -> Workbook:
    """Open ``path`` as a workbook, or raise :class:`InputError` saying why it cannot be."""
    return Workbook(path)


def is_workbook(path: Path) -> bool:
    """True when the file's suffix says it is a workbook this module reads."""
    return path.suffix.lower() in SUFFIXES


def check_readable(path: Path) -> None:
    """Refuse, with advice, a spreadsheet format this module cannot read."""
    kind = OTHER_FORMATS.get(path.suffix.lower())
    if kind:
        raise InputError(f"{path} is {kind}, which cannot be read", hint=SAVE_AS_HINT)


def _open_archive(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        try:
            with path.open("rb") as handle:
                protected = handle.read(len(_OLE_MAGIC)) == _OLE_MAGIC
        except OSError:
            protected = False
        if protected:
            raise InputError(
                f"{path} is protected with a password, or in the old binary format",
                hint=f"remove the password, or {SAVE_AS_HINT}",
            ) from None
        raise InputError(f"{path} is not an Excel workbook", hint=SAVE_AS_HINT) from None
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from None


def _elements(
    archive: zipfile.ZipFile, part: str, path: Path, name: str
) -> Iterator[ElementTree.Element]:
    """Each complete element called ``name`` (any namespace) in ``part``, streamed."""
    try:
        stream = archive.open(part)
    except KeyError:
        raise InputError(f"{path} is damaged: it has no {part}") from None
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        # An encrypted zip entry, or a compression method zipfile lacks.
        raise InputError(f"cannot read {part} in {path}: {exc}") from None
    parser = ElementTree.XMLPullParser(events=("end",))
    with stream:
        for chunk in _guarded(stream, part, path):
            yield from _parsed(parser, chunk, name, part, path)
    yield from _parsed(parser, None, name, part, path)


def _parsed(
    parser: ElementTree.XMLPullParser, chunk: bytes | None, name: str, part: str, path: Path
) -> list[ElementTree.Element]:
    """Feed ``chunk`` (``None`` at the end) and take the elements it completed."""
    try:
        if chunk is None:
            parser.close()
        else:
            parser.feed(chunk)
        # A parse error surfaces here, not in feed().
        return [item for _, item in parser.read_events() if _local(item.tag) == name]
    except ElementTree.ParseError as exc:
        raise InputError(f"{path} is damaged: {part}: {exc}") from None


def _guarded(stream: IO[bytes], part: str, path: Path) -> Iterator[bytes]:
    """The part's bytes, capped in size, refusing any document type declaration."""
    total = 0
    tail = b""
    while True:
        try:
            chunk = stream.read(_CHUNK if total else max(_CHUNK, _PROLOG))
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise InputError(f"{path} is damaged: {part}: {exc}") from None
        if not chunk:
            return
        if not total:
            _check_utf8(chunk, part, path)
        total += len(chunk)
        if total > MAX_PART_BYTES:
            raise InputError(
                f"{path} is too large to read: {part} inflates past "
                f"{MAX_PART_BYTES // (1024 * 1024)} MiB"
            )
        # Keep the end of the previous chunk, so a declaration split across two is seen.
        if _DOCTYPE in tail + chunk:
            raise InputError(f"{path} is not a workbook Office wrote: {part} declares a DTD")
        tail = chunk[-(len(_DOCTYPE) - 1) :]
        yield chunk


def _check_utf8(start: bytes, part: str, path: Path) -> None:
    """Refuse a part that is not UTF-8, so the byte check for a DTD means what it says."""
    text = start.removeprefix(_UTF8_BOM)
    declared = _ENCODING.match(text)
    unfinished = text.startswith(b"<?xml") and b"?>" not in text
    if (
        not text.startswith(b"<")
        or unfinished
        or (declared is not None and declared.group(1).lower() not in {b"utf-8", b"utf8"})
    ):
        raise InputError(f"{path} is not a workbook Office wrote: {part} is not UTF-8")


def _target(relationships: dict[str, tuple[str, str]], kind: str) -> str | None:
    return next((part for rel_kind, part in relationships.values() if rel_kind == kind), None)


def _rich_text(element: ElementTree.Element) -> str:
    """The text of a string item: a plain ``t``, or the ``t`` of each run, in order.

    Phonetic guides (``rPh``) are not part of the text, so they are left out.
    """
    parts = []
    for child in element:
        tag = _local(child.tag)
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local(child.tag) == name), None)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_index(letters: str) -> int:
    """Zero-based column: ``A`` -> 0, ``Z`` -> 25, ``AA`` -> 26."""
    index = 0
    for letter in letters.upper():
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1
