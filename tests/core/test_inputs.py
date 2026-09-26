import io
import logging
from datetime import date

import pytest

from fakes.workbooks import Styled, write_workbook
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.inputs import read_names
from libre_devops_helpers.core.row_filters import parse_conditions


def test_arguments_split_on_commas_and_spaces_and_drop_repeats():
    assert read_names(["web01,web02", "db01 WEB01"]) == ["web01", "web02", "db01"]


def test_dash_reads_stdin_in_place():
    stdin = io.StringIO("db01\n# a comment\n\ndb02  # inline\n")
    assert read_names(["web01", "-"], stdin=stdin) == ["web01", "db01", "db02"]


def test_dash_without_stdin_is_an_error():
    with pytest.raises(InputError, match="stdin"):
        read_names(["-"])


def test_a_text_file_holds_one_or_more_names_per_line(tmp_path):
    path = tmp_path / "hosts.txt"
    path.write_text("web01\nweb02,web03\n# retired: web04\n", encoding="utf-8")
    assert read_names(from_file=path) == ["web01", "web02", "web03"]


def test_a_csv_is_read_by_column_header_case_insensitively(tmp_path):
    path = tmp_path / "plan.csv"
    # A byte order mark, as Excel writes, must not end up in the first header.
    path.write_bytes(
        b"\xef\xbb\xbfFQDN,Ring,Notes\n"
        b'web01.example.com,1,"moved, then back"\n'
        b"db01.example.com,2,\n"
    )
    assert read_names(from_file=path, column="fqdn") == ["web01.example.com", "db01.example.com"]


def test_a_single_column_csv_needs_no_column_name(tmp_path):
    path = tmp_path / "groups.csv"
    path.write_text("Group\nMDE Pilot Devices\nLinux Servers\n", encoding="utf-8")
    # Cells are kept whole, so names with spaces survive.
    assert read_names(from_file=path) == ["MDE Pilot Devices", "Linux Servers"]


def test_a_csv_with_several_columns_asks_which(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("FQDN,Ring\nweb01,1\n", encoding="utf-8")
    with pytest.raises(InputError) as caught:
        read_names(from_file=path)
    assert "--column" in (caught.value.hint or "")
    with pytest.raises(InputError, match="no column"):
        read_names(from_file=path, column="hostname")


def test_a_csv_column_can_come_from_stdin():
    stdin = io.StringIO("name,os\nweb01,linux\nweb02,linux\n")
    assert read_names(["-"], stdin=stdin, column="name") == ["web01", "web02"]


def test_a_csv_header_may_sit_below_title_rows(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("Patch plan,,\n,,\nHost,FQDN,Ring\nweb01,web01.example.com,1\n", "utf-8")
    assert read_names(from_file=path, column="FQDN") == ["web01.example.com"]


def test_a_binary_file_that_is_not_a_workbook_is_refused(tmp_path):
    path = tmp_path / "hosts.bin"
    path.write_bytes(b"\xff\xfe\x00\x80")
    with pytest.raises(InputError, match="not a text file"):
        read_names(from_file=path)


PLAN = {
    "Summary": [["September patching"], ["Owner", "Platform team"]],
    "Ring 1": [
        ["Ring 1 servers"],
        [],
        ["Host", "FQDN", "Window"],
        ["web01", "web01.example.com", "Tue 02:00"],
        ["web02", None, "Tue 02:00"],
        ["db01", "  db01.example.com ", "Wed 02:00"],
        ["WEB01", "WEB01.example.com", "again"],
    ],
    "Retired": [["FQDN"], ["old01.example.com"]],
}


@pytest.fixture
def plan(tmp_path):
    return write_workbook(tmp_path / "plan.xlsx", PLAN, hidden_sheets=("Retired",))


def test_a_workbook_column_is_found_on_the_one_sheet_that_has_it(plan):
    # Title rows are skipped, blanks and repeats dropped, and cells trimmed.
    assert read_names(from_file=plan, column="fqdn") == ["web01.example.com", "db01.example.com"]


def test_a_hidden_sheet_is_read_only_when_named(plan):
    assert read_names(from_file=plan, column="FQDN", sheet="retired") == ["old01.example.com"]


def test_a_named_sheet_must_exist(plan):
    with pytest.raises(InputError, match="no sheet 'Ring 9'") as caught:
        read_names(from_file=plan, column="FQDN", sheet="Ring 9")
    assert caught.value.hint == "sheets: Summary, Ring 1, Retired"


def test_several_sheets_with_the_column_need_a_sheet(tmp_path):
    path = write_workbook(
        tmp_path / "rings.xlsm",
        {"Ring 1": [["FQDN"], ["web01"]], "Ring 2": [["fqdn"], ["web02"]]},
    )
    with pytest.raises(InputError, match="several sheets") as caught:
        read_names(from_file=path, column="FQDN")
    assert caught.value.hint == "pick one with --sheet (Ring 1, Ring 2)"
    assert read_names(from_file=path, column="FQDN", sheet="Ring 2") == ["web02"]


def test_no_sheet_with_the_column_lists_the_visible_sheets(plan):
    with pytest.raises(InputError, match=r"no sheet of .* has a column 'Hostname'") as caught:
        read_names(from_file=plan, column="Hostname")
    assert "(Summary, Ring 1)" in (caught.value.hint or "")


def test_without_a_column_the_first_visible_sheet_needs_a_single_column(tmp_path):
    path = write_workbook(
        tmp_path / "hosts.XLSX",
        {"Old": [["x"]], "Hosts": [["Name"], ["web01"], ["web02"]]},
        hidden_sheets=("Old",),
    )
    assert read_names(from_file=path) == ["web01", "web02"]
    two = write_workbook(tmp_path / "two.xlsx", {"Hosts": [["Name", "Ring"], ["web01", 1]]})
    with pytest.raises(InputError, match="several columns") as caught:
        read_names(from_file=two)
    assert caught.value.hint == "pick one with --column (Name, Ring)"


def test_a_workbook_of_hidden_sheets_needs_a_sheet(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", {"Old": [["FQDN"]]}, hidden_sheets=("Old",))
    with pytest.raises(InputError, match="only hidden sheets"):
        read_names(from_file=path, column="FQDN")


def test_hidden_rows_are_included_with_a_warning(tmp_path, caplog):
    path = write_workbook(
        tmp_path / "plan.xlsx",
        {
            "Plan": [
                ["FQDN", "Day"],
                ["web01", "Mon"],
                ["web02", "Tue"],
                ["web03", "Tue"],
                ["WEB02", "Tue"],
            ]
        },
        hidden_rows={"Plan": {2, 3, 4}},
    )
    with caplog.at_level(logging.WARNING):
        assert read_names(from_file=path, column="FQDN") == ["web01", "web02", "web03"]
    # web02 twice over is one name, and --where is the way to pick rows.
    assert "2 name(s) in sheet 'Plan'" in caplog.text
    assert "pick them by value with --where" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert read_names(from_file=path, column="FQDN", where=where("Day=Tue")) == [
            "web02",
            "web03",
        ]
    assert caplog.text == ""  # rows --where chose are meant, whatever Excel shows


def test_sheet_applies_to_workbooks_only(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("FQDN\nweb01\n", encoding="utf-8")
    with pytest.raises(InputError, match="--sheet"):
        read_names(from_file=path, sheet="Plan")
    with pytest.raises(InputError, match="--sheet"):
        read_names(["web01"], sheet="Plan")


def test_a_legacy_spreadsheet_gets_advice(tmp_path):
    path = tmp_path / "plan.xls"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1"))
    with pytest.raises(InputError, match="old binary Excel format") as caught:
        read_names(from_file=path, column="FQDN")
    assert caught.value.hint == "save it as .xlsx or .csv"


def where(*texts):
    return parse_conditions(texts, today=date(2026, 9, 25))


SCHEDULE = {
    "Plan": [
        ["Linux patching"],
        ["Server", "FQDN", "Scheduled Date", "Status"],
        ["web01", "web01.corp.example", Styled(46290, "dd/mm/yyyy"), ""],
        ["web02", "web02.corp.example", Styled(46291, "dd/mm/yyyy"), ""],
        ["db01", "db01.corp.example", Styled(46290, "dd/mm/yyyy"), "Done"],
        ["app07", "app07.corp.example", Styled(46290, "dd/mm/yyyy"), ""],
    ]
}


def test_a_workbooks_rows_are_filtered_by_their_dates_and_other_columns(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", SCHEDULE)
    found = read_names(
        from_file=path, column="FQDN", where=where("Scheduled Date=today", "Status!=Done")
    )
    assert found == ["web01.corp.example", "app07.corp.example"]
    tomorrow = read_names(from_file=path, column="FQDN", where=where("scheduled date=26/09/2026"))
    assert tomorrow == ["web02.corp.example"]


def test_a_named_sheets_rows_are_the_ones_filtered(tmp_path):
    rings = {
        "Ring 1": [["FQDN", "Scheduled Date"], ["web01.corp.example", Styled(46290, 14)]],
        "Ring 2": [
            ["FQDN", "Scheduled Date"],
            ["app07.corp.example", Styled(46290, 14)],
            ["db01.corp.example", Styled(46297, 14)],
        ],
    }
    path = write_workbook(tmp_path / "plan.xlsx", rings)
    found = read_names(
        from_file=path, column="FQDN", sheet="ring 2", where=where("Scheduled Date=last 7d")
    )
    assert found == ["app07.corp.example"]
    whole = read_names(
        from_file=path, column="FQDN", sheet="Ring 2", where=where("Scheduled Date=2026-09-01..")
    )
    assert whole == ["app07.corp.example", "db01.corp.example"]


def test_a_csvs_rows_are_filtered_the_same_way_uk_dates_and_all(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text(
        "Server,Scheduled Date\nweb01,25/09/2026\nweb02,26/09/2026\nweb03,01/10/2026\n",
        encoding="utf-8",
    )
    assert read_names(
        from_file=path, column="Server", where=where("Scheduled Date=2026-10-01")
    ) == ["web03"]


def test_names_given_as_arguments_are_kept_beside_the_filtered_rows(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", SCHEDULE)
    found = read_names(["extra01"], from_file=path, column="Server", where=where("Status=Done"))
    assert found == ["extra01", "db01"]


def test_a_filter_that_matches_nothing_says_what_the_column_holds(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", SCHEDULE)
    with pytest.raises(
        InputError, match=r"no rows of sheet 'Plan' .* match 'Scheduled Date=2026-12-25'"
    ) as caught:
        read_names(from_file=path, column="FQDN", where=where("Scheduled Date=2026-12-25"))
    assert caught.value.hint == "Scheduled Date holds: 2026-09-25, 2026-09-26"


def test_where_needs_a_table_and_its_column(tmp_path):
    path = write_workbook(tmp_path / "plan.xlsx", SCHEDULE)
    with pytest.raises(InputError, match="needs the column of names"):
        read_names(from_file=path, where=where("Status=Done"))
    with pytest.raises(InputError, match="filters the rows of a file"):
        read_names(["web01"], column="Server", where=where("Status=Done"))


def test_where_filters_a_csv_on_stdin_too():
    stdin = io.StringIO("Server,Status\nweb01,Done\nweb02,\n")
    assert read_names(["-"], stdin=stdin, column="Server", where=where("Status!=Done")) == ["web02"]
