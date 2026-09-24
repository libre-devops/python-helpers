import json
import re
import sys
from datetime import UTC, datetime

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand
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


def test_colour_json_is_json_dumps_with_colour():
    data = {"n": 1, "f": 2.5, "b": False, "z": None, "s": "é", "l": [{"x": []}, {}], "e": []}
    coloured = render.colour_json(data)
    assert "\x1b[" in coloured
    assert ANSI.sub("", coloured) == json.dumps(data, indent=2, ensure_ascii=False)
    compact = ANSI.sub("", render.colour_json(data, indent=None))
    assert compact == json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def test_brackets_share_a_colour_with_their_pair_by_depth():
    coloured = render.colour_json({"a": [{"b": 1}]})
    brackets = re.findall(r"\x1b\[38;5;(\d+)m\x1b\[1m([\[\]{}])", coloured)
    assert [char for _, char in brackets] == ["{", "[", "{", "}", "]", "}"]
    colours = [colour for colour, _ in brackets]
    assert colours[0] == colours[5]
    assert colours[1] == colours[4]
    assert colours[2] == colours[3]
    assert len({colours[0], colours[1], colours[2]}) == 3


def test_colour_is_only_for_a_terminal_without_no_color(monkeypatch):
    class Terminal:
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert render.colour_wanted(Terminal())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not render.colour_wanted(Terminal())
    assert not render.colour_wanted(object())


def test_print_json_colours_on_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(render, "colour_wanted", lambda stream=None: True)
    render.print_json({"when": datetime(2026, 9, 24, tzinfo=UTC)})
    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert ANSI.sub("", out) == '{\n  "when": "2026-09-24T00:00:00+00:00"\n}\n'
