"""Excel workbooks built by hand, laid out as Excel saves them."""

import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

STRICT_MAIN_NS = "http://purl.oclc.org/ooxml/spreadsheetml/main"

STRICT_REL_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"

Cell = str | int | float | bool | None


def workbook_parts(
    sheets: dict[str, list[list[Cell]]],
    *,
    hidden_sheets: tuple[str, ...] = (),
    hidden_rows: dict[str, set[int]] | None = None,
    strict: bool = False,
) -> dict[str, str]:
    """The XML parts of a workbook laid out as Excel saves one, with shared strings.

    ``hidden_rows`` maps a sheet to the zero-based indexes of its hidden rows. Blank
    cells (``None`` or ``""``) are left out of the XML, as Excel leaves them out.
    """
    main, rel = (STRICT_MAIN_NS, STRICT_REL_NS) if strict else (MAIN_NS, REL_NS)
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    strings: list[str] = []
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
                if isinstance(value, bool):
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
    parts["xl/workbook.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>{"".join(entries)}</sheets></workbook>'
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


def write_zip(path: Path, parts: dict[str, str | bytes]) -> Path:
    """Write ``parts`` into a zip at ``path``, deflated as Office does."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def write_workbook(path: Path, sheets: dict[str, list[list[Cell]]], **options: Any) -> Path:
    """Write a workbook of ``sheets`` (tab name -> rows of cells) to ``path``."""
    return write_zip(path, dict(workbook_parts(sheets, **options)))
