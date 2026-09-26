import json

import pytest

from libre_devops_helpers.core import colour, yaml_text


class Terminal:
    def isatty(self):
        return True


def test_colour_is_as_asked_else_no_color_or_force_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert colour.setting() is None
    monkeypatch.setenv("FORCE_COLOR", "0")
    assert colour.setting() is None
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colour.setting() is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert colour.setting() is False  # NO_COLOR wins over FORCE_COLOR
    colour.use(True)
    assert colour.setting() is True  # and what was asked over both
    assert colour.wanted(object())
    colour.use(False)
    assert not colour.wanted(Terminal())


def test_left_alone_colour_is_only_for_a_terminal(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert colour.wanted(Terminal())
    assert not colour.wanted(object())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not colour.wanted(Terminal())


def test_styles_are_the_ansi_codes_typer_writes():
    import typer

    for fg, bold in ((75, False), (75, True), ("green", False), ("bright_black", True)):
        assert colour.style("x", fg, bold=bold) == typer.style("x", fg=fg, bold=bold or None)
    assert colour.style("x", bold=True) == typer.style("x", bold=True)
    assert colour.style("x", dim=True) == typer.style("x", dim=True)
    assert colour.style("plain") == "plain"  # nothing to apply, so no reset either
    assert colour.strip(colour.style("web01", "red", bold=True)) == "web01"


def test_colour_json_is_json_dumps_with_colour():
    data = {"n": 1, "f": 2.5, "b": False, "z": None, "s": "é", "l": [{"x": []}, {}], "e": []}
    coloured = colour.json_text(data)
    assert "\x1b[" in coloured
    assert colour.strip(coloured) == json.dumps(data, indent=2, ensure_ascii=False)
    compact = colour.strip(colour.json_text(data, indent=None))
    assert compact == json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    keyed = colour.strip(colour.json_text({"b": 1, "a": 2}, sort_keys=True))
    assert keyed == json.dumps({"a": 2, "b": 1}, indent=2)


def test_brackets_share_a_colour_with_their_pair_by_depth():
    import re

    coloured = colour.json_text({"a": [{"b": 1}]})
    brackets = re.findall(r"\x1b\[38;5;(\d+)m\x1b\[1m([\[\]{}])", coloured)
    assert [char for _, char in brackets] == ["{", "[", "{", "}", "]", "}"]
    colours = [code for code, _ in brackets]
    assert colours[0] == colours[5]
    assert colours[1] == colours[4]
    assert colours[2] == colours[3]
    assert len({colours[0], colours[1], colours[2]}) == 3


def test_yaml_takes_the_json_palette():
    painted = yaml_text.dumps({"on": True, "n": None}, paint=colour.paint)
    assert colour.strip(painted) == yaml_text.dumps({"on": True, "n": None})
    assert colour.style('"on"', 75, bold=True) in painted
    assert colour.paint("punct", ":") == ":"


def test_the_rainbow_runs_in_diagonal_bands():
    line = "x" * 12
    first, second = colour.diagonal(line, 0), colour.diagonal(line, 3)
    assert colour.strip(first) == colour.strip(second) == line
    assert first.count("\x1b[38;5;") == 2  # two bands of six
    assert first != second  # a later row starts further along the rainbow
    assert colour.diagonal("", 0) == ""


def test_a_hex_colour_is_exact_where_the_terminal_shows_24_bit(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert colour.style("x", "#1E3A8A") == "\x1b[38;2;30;58;138mx\x1b[0m"
    assert colour.style("x", "#1E3A8A", bg="#F97316") == (
        "\x1b[38;2;30;58;138m\x1b[48;2;249;115;22mx\x1b[0m"
    )


@pytest.mark.parametrize(
    ("environ", "shown"),
    [
        ({"COLORTERM": "24bit"}, True),
        ({"WT_SESSION": "abc"}, True),
        ({"COLORTERM": "yes"}, False),
        ({}, False),
    ],
    ids=["24bit", "windows-terminal", "other", "nothing"],
)
def test_24_bit_colour_is_what_the_terminal_says(monkeypatch, environ, shown):
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    assert colour.truecolour() is shown


def test_elsewhere_a_hex_colour_is_the_nearest_of_the_256(monkeypatch):
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert colour.style("x", "#1E3A8A") == "\x1b[38;5;24mx\x1b[0m"
    assert (colour.nearest("#F97316"), colour.nearest("#FFFFFF")) == (202, 231)
    assert colour.nearest("#808080") == 244  # a grey is nearer the grey ramp than the cube


def test_a_named_or_numbered_colour_can_go_behind_too():
    assert colour.style("x", "white", bg="red") == "\x1b[37m\x1b[41mx\x1b[0m"
    assert colour.style("x", bg=53) == "\x1b[48;5;53mx\x1b[0m"
