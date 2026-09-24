import zipfile

import pytest

from fakes.workbooks import MAIN_NS, workbook_parts, write_workbook, write_zip
from libre_devops_helpers.core import sheets
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.sheets import SheetRow, open_workbook


def cells(path, name=None):
    with open_workbook(path) as book:
        sheet = book.sheet(name) if name else book.sheets[0]
        return [row.cells for row in book.rows(sheet)]


def with_sheet_xml(tmp_path, sheet_data, *, strings=""):
    """A one-sheet workbook whose sheet data and shared strings are given as raw XML."""
    parts = workbook_parts({"Plan": []})
    parts["xl/worksheets/sheet1.xml"] = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{sheet_data}</sheetData></worksheet>'
    )
    parts["xl/sharedStrings.xml"] = f'<sst xmlns="{MAIN_NS}">{strings}</sst>'
    return write_zip(tmp_path / "plan.xlsx", parts)


def test_rows_come_back_as_text_with_shared_strings_resolved(tmp_path):
    path = write_workbook(
        tmp_path / "plan.xlsx",
        {"Plan": [["Host", "Ring", "Critical"], ["web01", 1, True], ["db01", 2.5, False]]},
    )
    assert cells(path) == [
        ["Host", "Ring", "Critical"],
        ["web01", "1", "TRUE"],
        ["db01", "2.5", "FALSE"],
    ]


def test_every_kind_of_cell_value_is_read_as_excel_saved_it(tmp_path):
    path = with_sheet_xml(
        tmp_path,
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c>'  # rich text, with a phonetic guide to leave out
        '<c r="B1" t="inlineStr"><is><t>inline</t></is></c>'
        '<c r="C1" t="str"><f>A1&amp;"x"</f><v>cached result</v></c>'  # formula: value only
        '<c r="D1" t="e"><v>#N/A</v></c>'
        '<c r="E1" t="d"><v>2026-09-24T00:00:00</v></c>'
        '<c r="F1" s="1"/>'  # styled but empty
        "</row>",
        strings="<si><r><t>web</t></r><r><rPr><b/></rPr><t>01</t></r><rPh><t>x</t></rPh></si>",
    )
    assert cells(path) == [["web01", "inline", "cached result", "", "2026-09-24T00:00:00", ""]]


def test_cell_references_place_values_in_their_columns(tmp_path):
    path = with_sheet_xml(
        tmp_path,
        '<row r="1"><c r="B1" t="inlineStr"><is><t>b</t></is></c>'
        '<c r="AA1"><v>27</v></c></row>'
        # Without references, cells follow one another from column A.
        '<row><c t="inlineStr"><is><t>a</t></is></c><c><v>2</v></c></row>',
    )
    first, second = cells(path)
    assert first == ["", "b"] + [""] * 24 + ["27"]
    assert second == ["a", "2"]


def test_hidden_sheets_and_rows_are_flagged_and_chart_sheets_skipped(tmp_path):
    parts = workbook_parts(
        {"Plan": [["FQDN"], ["web01"], ["db01"]], "Old": [["FQDN"]]},
        hidden_sheets=("Old",),
        hidden_rows={"Plan": {2}},
    )
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        "</sheets>", '<sheet name="Chart" sheetId="9" r:id="rId9"/></sheets>'
    )
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>",
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/chartsheet" Target="chartsheets/sheet1.xml"/></Relationships>',
    )
    path = write_zip(tmp_path / "plan.xlsx", parts)
    with open_workbook(path) as book:
        assert [(sheet.name, sheet.hidden) for sheet in book.sheets] == [
            ("Plan", False),
            ("Old", True),
        ]
        assert list(book.rows(book.sheet("plan"))) == [
            SheetRow(["FQDN"], False),
            SheetRow(["web01"], False),
            SheetRow(["db01"], True),
        ]


def test_the_strict_flavour_and_absolute_targets_are_understood(tmp_path):
    parts = workbook_parts({"Plan": [["FQDN"], ["web01"]]}, strict=True)
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        'Target="worksheets/', 'Target="/xl/worksheets/'
    )
    assert cells(write_zip(tmp_path / "plan.xlsx", parts)) == [["FQDN"], ["web01"]]


def test_a_workbook_without_shared_strings_still_reads(tmp_path):
    parts = workbook_parts({"Plan": [[1], [2]]})
    del parts["xl/sharedStrings.xml"]
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "sharedStrings", "styles"
    )
    assert cells(write_zip(tmp_path / "plan.xlsx", parts)) == [["1"], ["2"]]


def test_an_unknown_sheet_lists_the_sheets(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", {"Ring 1": [], "Ring 2": []})
    with open_workbook(path) as book, pytest.raises(InputError) as caught:
        book.sheet("Ring 3")
    assert caught.value.hint == "sheets: Ring 1, Ring 2"


def test_a_file_that_is_not_a_zip_is_not_a_workbook(tmp_path):
    path = tmp_path / "plan.xlsx"
    path.write_text("FQDN\nweb01\n", encoding="utf-8")
    with pytest.raises(InputError, match="not an Excel workbook") as caught:
        open_workbook(path)
    assert ".csv" in (caught.value.hint or "")


def test_a_password_protected_or_legacy_file_says_so(tmp_path):
    path = tmp_path / "plan.xlsx"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 512)
    with pytest.raises(InputError, match="password") as caught:
        open_workbook(path)
    assert "remove the password" in (caught.value.hint or "")


def test_a_zip_that_is_not_a_workbook_is_refused(tmp_path):
    path = write_zip(tmp_path / "plan.xlsx", {"readme.txt": "hello"})
    with pytest.raises(InputError, match="not an Excel workbook"):
        open_workbook(path)


def test_a_missing_part_or_shared_string_is_reported_as_damage(tmp_path):
    parts = workbook_parts({"Plan": [["web01"]]})
    del parts["xl/worksheets/sheet1.xml"]
    path = write_zip(tmp_path / "gone.xlsx", parts)
    with open_workbook(path) as book, pytest.raises(InputError, match="damaged"):
        list(book.rows(book.sheets[0]))
    path = with_sheet_xml(tmp_path, '<row><c t="s"><v>5</v></c></row>')
    with pytest.raises(InputError, match="missing shared string"):
        cells(path)


def test_malformed_xml_is_reported_as_damage(tmp_path):
    path = with_sheet_xml(tmp_path, "<row><c><v>1</v></row>")
    with pytest.raises(InputError, match="damaged"):
        cells(path)


def test_a_document_type_declaration_is_refused_before_parsing(tmp_path, monkeypatch):
    laughs = (
        '<?xml version="1.0"?><!-- ' + "padding " * 200 + '--><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData><row><c t="inlineStr"><is><t>&lol2;</t>'
        "</is></c></row></sheetData></worksheet>"
    )
    parts = workbook_parts({"Plan": []})
    parts["xl/worksheets/sheet1.xml"] = laughs
    path = write_zip(tmp_path / "plan.xlsx", parts)
    with pytest.raises(InputError, match="DTD"):
        cells(path)
    # A declaration split across two reads is caught all the same.
    split = laughs.index("<!DOCTYPE") + 4
    monkeypatch.setattr(sheets, "_CHUNK", split - sheets._PROLOG)
    with pytest.raises(InputError, match="DTD"):
        cells(path)


@pytest.mark.parametrize(
    "content",
    [
        '<?xml version="1.0" encoding="cp037"?><worksheet/>',
        '<?xml version="1.0" encoding="UTF-16"?><worksheet/>',
        '<?xml version="1.0" encoding="utf-8"?><worksheet/>'.encode("utf-16"),
        b'<?xml version="1.0"' + b" " * 70_000 + b"?><worksheet/>",
    ],
)
def test_a_part_in_another_encoding_is_refused(tmp_path, content):
    parts: dict[str, str | bytes] = dict(workbook_parts({"Plan": []}))
    parts["xl/worksheets/sheet1.xml"] = content
    with pytest.raises(InputError, match="not UTF-8"):
        cells(write_zip(tmp_path / "plan.xlsx", parts))


def test_utf8_with_a_byte_order_mark_is_fine(tmp_path):
    parts: dict[str, str | bytes] = dict(workbook_parts({"Plan": []}))
    parts["xl/worksheets/sheet1.xml"] = (
        b"\xef\xbb\xbf"
        + f'<worksheet xmlns="{MAIN_NS}"><sheetData><row><c><v>1</v></c></row></sheetData>'
        "</worksheet>".encode()
    )
    assert cells(write_zip(tmp_path / "plan.xlsx", parts)) == [["1"]]


def test_a_part_that_inflates_too_far_is_refused(tmp_path, monkeypatch):
    rows = [[f"web{number:04}.example.com"] for number in range(2000)]
    path = write_workbook(tmp_path / "plan.xlsx", {"Plan": rows})
    monkeypatch.setattr(sheets, "MAX_PART_BYTES", 4096)
    with pytest.raises(InputError, match="too large"):
        open_workbook(path)  # the shared strings are read on open


def test_a_corrupt_zip_entry_is_reported_as_damage(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", {"Plan": [["web01"]]})
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("xl/worksheets/sheet1.xml")
    # Flip bytes inside the compressed sheet so inflating it, or its CRC, fails.
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    for offset in range(start, start + info.compress_size):
        data[offset] ^= 0xFF
    path.write_bytes(bytes(data))
    with open_workbook(path) as book, pytest.raises(InputError):
        list(book.rows(book.sheets[0]))


@pytest.mark.parametrize("suffix", [".xls", ".xlsb", ".ods", ".numbers", ".XLS"])
def test_other_spreadsheet_formats_get_advice(tmp_path, suffix):
    with pytest.raises(InputError, match="cannot be read") as caught:
        sheets.check_readable(tmp_path / f"plan{suffix}")
    assert caught.value.hint == "save it as .xlsx or .csv"


def test_workbook_suffixes_are_matched_case_insensitively(tmp_path):
    assert all(
        sheets.is_workbook(tmp_path / f"plan{suffix}")
        for suffix in (".xlsx", ".XLSM", ".xltx", ".xltm")
    )
    assert not sheets.is_workbook(tmp_path / "plan.csv")
