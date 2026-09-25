import json
import re
import sys
from datetime import UTC, datetime

import pytest
import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand, colour
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.tables import QueryResult

ESC = "\x1b["


def as_terminal(monkeypatch) -> None:
    """Make stderr claim to be a terminal and clear the banner variables.

    Call it in the test itself: pytest swaps sys.stderr between fixture setup and the
    test body, so a patch made in a fixture would land on the wrong stream.
    """
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.delenv(brand.env_var("NO_BANNER"), raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)


def test_the_banner_is_coloured_on_a_terminal(monkeypatch, capsys):
    as_terminal(monkeypatch)
    render.banner()
    err = capsys.readouterr().err
    assert ESC in err
    assert f"{brand.DISPLAY_NAME}  {brand.COMMAND}" in err


def test_no_color_keeps_the_banner_but_drops_the_colour(monkeypatch, capsys):
    as_terminal(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    render.banner()
    err = capsys.readouterr().err
    first = brand.BANNER.strip("\n").splitlines()[0]
    assert first in err.splitlines()


def test_the_banner_stays_out_of_pipes_and_when_turned_off(monkeypatch, capsys):
    as_terminal(monkeypatch)
    monkeypatch.setenv(brand.env_var("NO_BANNER"), "1")
    render.banner()
    assert capsys.readouterr().err == ""
    render.banner(force=True)
    assert brand.DISPLAY_NAME in capsys.readouterr().err
    monkeypatch.delenv(brand.env_var("NO_BANNER"))
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    render.banner()
    assert capsys.readouterr().err == ""


def test_query_cells_flatten_nested_values_to_json(capsys):
    when = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    result = QueryResult.from_records(
        [
            {
                "name": "vm1",
                "tags": {"env": "prod"},
                "seen": [when],
                "count": 3,
                "on": True,
                "gone": None,
                "other": Output.TABLE,
            }
        ],
        truncated=True,
    )
    render.query_result(result, Output.CSV)
    captured = capsys.readouterr()
    header, row = captured.out.splitlines()
    assert header == "name,tags,seen,count,on,gone,other"
    cells = row.split(",", 1)
    assert cells[0] == "vm1"
    assert '""env"": ""prod""' in cells[1]
    assert "2026-09-24T12:00:00+00:00" in cells[1]
    assert row.endswith(",3,True,,table")
    assert "raise --limit to fetch more" in captured.err


def test_query_results_as_json_are_the_rows(capsys):
    render.query_result(QueryResult.from_records([{"a": 1}]), Output.JSON)
    assert json.loads(capsys.readouterr().out) == [{"a": 1}]


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_print_json_colours_on_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(colour, "wanted", lambda stream=None: True)
    render.print_json({"when": datetime(2026, 9, 24, tzinfo=UTC)})
    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert ANSI.sub("", out) == '{\n  "when": "2026-09-24T00:00:00+00:00"\n}\n'


def test_a_date_the_platform_cannot_convert_is_shown_in_utc(monkeypatch):
    class Unconvertible(datetime):
        def astimezone(self, tz=None):
            raise OverflowError("date value out of range")

    value = Unconvertible(1969, 12, 31, 23, 0, tzinfo=UTC)
    assert render.when(value, now=datetime(2026, 9, 25, tzinfo=UTC)).startswith(
        "1969-12-31 23:00 UTC ("
    )


def test_tsv_is_values_only_one_row_a_line_like_az():
    rows = [["web01", ("ok", "green"), "a\tb"], ["db01", "", "line one\nline two"]]
    assert render.tsv_text(rows) == "web01\tok\ta b\ndb01\t\tline one line two\n"
    assert render.tsv_text([]) == ""


def test_emit_writes_tsv_without_a_header(capsys):
    render.emit(Output.TSV, ["NAME", "STATE"], [["web01", "on"]], None)
    assert capsys.readouterr().out == "web01\ton\n"


def test_a_table_fits_the_window_by_cutting_its_last_column():
    long = "Microsoft Graph: HTTP 403 Forbidden: Missing application scopes. " * 3
    text = render.table(["COMMAND", "RESULT", "DETAIL"], [["xdr hunt", "refused", long]], width=60)
    lines = [ANSI.sub("", line) for line in text.splitlines()]
    assert all(len(line) <= 60 for line in lines)
    assert lines[2].endswith("…")
    # The last column gets what is left of 60: less the two columns before it and the gaps.
    assert lines[1].split()[-1] == "-" * (60 - len("xdr hunt") - len("refused") - 2 * 2)


def test_piped_tables_keep_every_character():
    long = "x" * 500
    text = render.table(["A", "DETAIL"], [["a", long]])  # stdout is not a terminal here
    assert long in text


def arranged_names(capsys, output=Output.CSV):
    headers = ["DEVICE", "SEVERITY", "LAST SEEN"]
    rows = [
        ["web10", ("High", "red"), "2026-09-01 10:00 (24d ago)"],
        ["web2", ("Critical", "red"), "-"],
        ["WEB2", ("Low", None), "2026-09-20 10:00 (5d ago)"],
        ["db01", ("High", "red"), "2026-09-24 10:00 (1d ago)"],
    ]
    render.emit(output, headers, rows, [{"device": row[0]} for row in rows])
    out = capsys.readouterr().out
    return [line.split(",")[0] for line in out.splitlines()[1:]] if output is Output.CSV else out


def test_rows_come_as_they_are_unless_sorted(capsys):
    assert arranged_names(capsys) == ["web10", "web2", "WEB2", "db01"]


def test_sort_by_several_columns_most_significant_first(capsys):
    render.sort_rows(["severity:desc", "device"])
    assert arranged_names(capsys) == ["web2", "db01", "web10", "WEB2"]


def test_unique_after_sort_keeps_the_newest_of_each(capsys):
    render.sort_rows(["last_seen:desc"])
    render.unique_rows(["Device"])
    # web2 is blank for LAST SEEN, so sorts last and its later twin WEB2 is kept.
    assert arranged_names(capsys) == ["db01", "WEB2", "web10"]


def test_arranged_tables_and_tsv_too(capsys):
    render.sort_rows(["device"])
    table = ANSI.sub("", arranged_names(capsys, Output.TABLE)).splitlines()
    assert [line.split()[0] for line in table[2:]] == ["db01", "web2", "WEB2", "web10"]
    render.unique_rows(["device"])
    tsv = arranged_names(capsys, Output.TSV).splitlines()
    assert [line.split("\t")[0] for line in tsv] == ["db01", "web2", "web10"]


def test_json_is_left_as_it_is_with_a_pointer_to_jq(capsys):
    render.sort_rows(["device:desc"])
    out = arranged_names(capsys, Output.JSON)
    assert [item["device"] for item in json.loads(out)] == ["web10", "web2", "WEB2", "db01"]
    render.query_result(QueryResult.from_records([{"a": 1}]), Output.JSON)
    assert capsys.readouterr().err.count("for JSON use jq's sort_by") == 1


def test_an_unknown_column_names_the_ones_there_are(capsys):
    render.unique_rows(["owner"])
    with pytest.raises(InputError, match="no 'owner' column") as caught:
        arranged_names(capsys)
    assert caught.value.hint == "columns: DEVICE, SEVERITY, LAST SEEN"


def test_a_sort_without_a_direction_it_knows_is_a_usage_error():
    with pytest.raises(typer.BadParameter, match="cannot sort by 'device:up'"):
        render.sort_rows(["device:up"])


def test_query_results_sort_by_their_columns(capsys):
    render.sort_rows(["count:desc"])
    rows = [{"Name": "a", "Count": 2}, {"Name": "b", "Count": 10}, {"Name": "c", "Count": None}]
    render.query_result(QueryResult.from_records(rows), Output.TSV)
    assert capsys.readouterr().out == "b\t10\na\t2\nc\t\n"


def test_a_moment_is_local_time_to_the_second_or_utc_where_it_cannot_be():
    class Unconvertible(datetime):
        def astimezone(self, tz=None):
            raise OverflowError("date value out of range")

    assert render.moment(None) == "-"
    at = datetime(2026, 9, 24, 8, 0, 5, tzinfo=UTC)
    assert render.moment(at) == f"{at.astimezone():%Y-%m-%d %H:%M:%S}"
    old = Unconvertible(1969, 12, 31, 23, 0, 5, tzinfo=UTC)
    assert render.moment(old) == "1969-12-31 23:00:05 UTC"
