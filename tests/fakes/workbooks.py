"""Excel workbooks built by hand, laid out as Excel saves them."""

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

STRICT_MAIN_NS = "http://purl.oclc.org/ooxml/spreadsheetml/main"

STRICT_REL_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"


@dataclass(frozen=True)
class Styled:
    """A number with a number format, as Excel keeps a date: ``Styled(46290, 14)`` is
    25/09/2026 in built-in format 14, ``Styled(0.375, "hh:mm")`` 09:00 in a format of the
    workbook's own."""

    value: float
    format: int | str


Cell = str | int | float | bool | Styled | None


def workbook_parts(
    sheets: dict[str, list[list[Cell]]],
    *,
    hidden_sheets: tuple[str, ...] = (),
    hidden_rows: dict[str, set[int]] | None = None,
    strict: bool = False,
    date1904: bool = False,
) -> dict[str, str]:
    """The XML parts of a workbook laid out as Excel saves one, with shared strings.

    ``hidden_rows`` maps a sheet to the zero-based indexes of its hidden rows. Blank
    cells (``None`` or ``""``) are left out of the XML, as Excel leaves them out. A
    ``Styled`` cell gets a cell format in a styles part; ``date1904`` counts dates from 1904.
    """
    main, rel = (STRICT_MAIN_NS, STRICT_REL_NS) if strict else (MAIN_NS, REL_NS)
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    strings: list[str] = []
    # Cell format 0 is General, as in every workbook; each distinct Styled format follows.
    formats: list[int | str] = []
    parts: dict[str, str] = {}
    entries, links = [], []
    for number, (name, rows) in enumerate(sheets.items(), start=1):
        state = ' state="hidden"' if name in hidden_sheets else ""
        tab = escape(name, {'"': "&quot;"})
        entries.append(f'<sheet name="{tab}" sheetId="{number}"{state} r:id="rId{number}"/>')
        links.append(
            f'<Relationship Id="rId{number}" Type="{rel}/worksheet" '
            f'Target="worksheets/sheet{number}.xml"/>'
        )
        body = []
        for row_index, row in enumerate(rows):
            cells = []
            for column, value in enumerate(row):
                ref = f"{chr(ord('A') + column)}{row_index + 1}"
                if value is None or value == "":
                    continue
                if isinstance(value, Styled):
                    if value.format not in formats:
                        formats.append(value.format)
                    style = formats.index(value.format) + 1
                    cells.append(f'<c r="{ref}" s="{style}"><v>{value.value}</v></c>')
                elif isinstance(value, bool):
                    cells.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
                elif isinstance(value, int | float):
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    if value not in strings:
                        strings.append(value)
                    cells.append(f'<c r="{ref}" t="s"><v>{strings.index(value)}</v></c>')
            hidden = ' hidden="1"' if row_index in (hidden_rows or {}).get(name, set()) else ""
            body.append(f'<row r="{row_index + 1}"{hidden}>{"".join(cells)}</row>')
        parts[f"xl/worksheets/sheet{number}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{main}"><sheetData>{"".join(body)}</sheetData></worksheet>'
        )
    links.append(
        f'<Relationship Id="rId{len(sheets) + 1}" Type="{rel}/sharedStrings" '
        'Target="sharedStrings.xml"/>'
    )
    items = "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
    parts["xl/sharedStrings.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<sst xmlns="{main}" count="{len(strings)}">{items}</sst>'
    )
    if formats:
        links.append(
            f'<Relationship Id="rId{len(sheets) + 2}" Type="{rel}/styles" Target="styles.xml"/>'
        )
        parts["xl/styles.xml"] = _styles(main, formats)
    properties = '<workbookPr date1904="1"/>' if date1904 else ""
    parts["xl/workbook.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="{main}" xmlns:r="{rel}">{properties}'
        f"<sheets>{''.join(entries)}</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{package_rel}">{"".join(links)}</Relationships>'
    )
    parts["_rels/.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{package_rel}"><Relationship Id="rId1" '
        f'Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    )
    return parts


def _styles(main: str, formats: list[int | str]) -> str:
    """A styles part: a numFmt for each format code, and a cell format for each format, after
    General. The cellStyleXfs before them hold xf elements too, which a reader must not take
    for cell formats, so there is one here."""
    custom = [code for code in formats if isinstance(code, str)]
    codes = "".join(
        f'<numFmt numFmtId="{164 + i}" formatCode="{escape(code, {chr(34): "&quot;"})}"/>'
        for i, code in enumerate(custom)
    )
    ids = [code if isinstance(code, int) else 164 + custom.index(code) for code in formats]
    xfs = "".join(f'<xf numFmtId="{format_id}" applyNumberFormat="1"/>' for format_id in ids)
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<styleSheet xmlns="{main}"><numFmts count="{len(custom)}">{codes}</numFmts>'
        '<cellStyleXfs count="1"><xf numFmtId="22"/></cellStyleXfs>'
        f'<cellXfs count="{len(ids) + 1}"><xf numFmtId="0"/>{xfs}</cellXfs></styleSheet>'
    )


def write_zip(path: Path, parts: dict[str, str | bytes]) -> Path:
    """Write ``parts`` into a zip at ``path``, deflated as Office does."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def write_workbook(path: Path, sheets: dict[str, list[list[Cell]]], **options: Any) -> Path:
    """Write a workbook of ``sheets`` (tab name -> rows of cells) to ``path``."""
    return write_zip(path, dict(workbook_parts(sheets, **options)))
