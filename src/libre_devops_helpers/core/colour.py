"""Colour: whether to use it, and the styles and palettes that apply it.

One decision for everything written: what was asked (``use``, from ``--colour`` or
``--no-colour``), else ``NO_COLOR`` (off), else ``FORCE_COLOR`` (on), else colour only
on a terminal. Colour is ANSI escape codes, so nothing here needs a library, and
``strip`` takes them out again.

JSON and YAML share one palette, keys, strings, numbers, booleans and null each with a
colour, and brackets take the rainbow by how deeply they nest.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

# The rainbow (256-colour codes, red through to pink): the banner's bands, and brackets.
RAINBOW = (196, 208, 226, 46, 51, 33, 129, 201)

# A kind of value ("key", "string", "number", "bool", "null", "punct") and its style: a
# 256-colour code, or None for none, and whether it is bold.
PALETTE: dict[str, tuple[int | None, bool]] = {
    "key": (75, True),
    "string": (114, False),
    "number": (215, False),
    "bool": (176, False),
    "null": (244, False),
    "punct": (None, False),
}

# The eight terminal colours by name, as click names them; bright_ ones are 60 higher.
_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
_CODES = {name: 30 + index for index, name in enumerate(_NAMES)} | {
    f"bright_{name}": 90 + index for index, name in enumerate(_NAMES)
}
_RESET = "\x1b[0m"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class _Choice:
    """What was asked: colour (True), none (False), or left to the terminal (None)."""

    value: bool | None = None


def use(choice: bool | None) -> None:
    """``--colour`` (True), ``--no-colour`` (False), or neither (None)."""
    _Choice.value = choice


def setting() -> bool | None:
    """Colour on, off, or None for "on a terminal": what was asked, else ``NO_COLOR``
    (off), else ``FORCE_COLOR`` (on, unless it is 0), else None."""
    if _Choice.value is not None:
        return _Choice.value
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("FORCE_COLOR", "")
    if force and force != "0":
        return True
    return None


def wanted(stream: Any = None) -> bool:
    """Whether to colour ``stream`` (stdout by default): as decided, else when a terminal."""
    decided = setting()
    if decided is not None:
        return decided
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def style(text: str, fg: int | str | None = None, *, bold: bool = False, dim: bool = False) -> str:
    """``text`` in ``fg`` (a 256-colour code, or a name such as ``green``), and bold or
    dim, as ANSI codes; plain ``text`` when there is nothing to apply."""
    codes = []
    if isinstance(fg, int):
        codes.append(f"\x1b[38;5;{fg}m")
    elif fg is not None:
        codes.append(f"\x1b[{_CODES[fg]}m")
    if bold:
        codes.append("\x1b[1m")
    if dim:
        codes.append("\x1b[2m")
    return "".join(codes) + text + _RESET if codes else text


def strip(text: str) -> str:
    """``text`` without its colour."""
    return _ANSI.sub("", text)


def paint(kind: str, text: str) -> str:
    """``text`` in the palette's style for ``kind``: a painter for ``yaml_text.dumps``."""
    fg, bold = PALETTE[kind]
    return style(text, fg, bold=bold)


def diagonal(line: str, row: int, band: int = 6) -> str:
    """``line`` (row ``row`` of some art) in rainbow bands ``band`` wide that run along
    the diagonal, so any art gets the same sweep; one style per run of a colour."""
    parts: list[str] = []
    run: list[str] = []
    current: int | None = None
    for column, char in enumerate(line):
        colour = RAINBOW[((column + 2 * row) // band) % len(RAINBOW)]
        if colour != current and run:
            parts.append(style("".join(run), current, bold=True))
            run = []
        current = colour
        run.append(char)
    if run:
        parts.append(style("".join(run), current, bold=True))
    return "".join(parts)


def json_text(
    data: Any, *, indent: int | None = 2, sort_keys: bool = False, ensure_ascii: bool = False
) -> str:
    """``data`` (plain JSON values) laid out as ``json.dumps`` would, in colour.

    Brackets are coloured by how deeply they nest, so matching pairs share one. Strip the
    colour and the text is exactly ``json.dumps(data, indent=indent)``.
    """
    return _JsonLayout(indent, sort_keys, ensure_ascii).value(data, 0)


@dataclass(frozen=True)
class _JsonLayout:
    """``json.dumps``'s layout, written one value at a time so each can be painted."""

    indent: int | None
    sort_keys: bool
    ensure_ascii: bool

    def value(self, value: Any, depth: int) -> str:
        if isinstance(value, dict):
            items = sorted(value.items()) if self.sort_keys else list(value.items())
            colon = ": " if self.indent is not None else ":"
            members = [
                paint("key", self._dumps(str(key))) + colon + self.value(item, depth + 1)
                for key, item in items
            ]
            return self._enclose("{", members, "}", depth)
        if isinstance(value, list):
            return self._enclose("[", [self.value(item, depth + 1) for item in value], "]", depth)
        return paint(_kind(value), self._dumps(value))

    def _enclose(self, opening: str, parts: list[str], closing: str, depth: int) -> str:
        """``parts`` between a bracket pair, one to a line when indented."""
        colour = RAINBOW[depth % len(RAINBOW)]
        if not parts:
            inside = ""
        elif self.indent is None:
            inside = ",".join(parts)
        else:
            line = "\n" + " " * (self.indent * (depth + 1))
            inside = line + ("," + line).join(parts) + "\n" + " " * (self.indent * depth)
        return style(opening, colour, bold=True) + inside + style(closing, colour, bold=True)

    def _dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=self.ensure_ascii)


def _kind(value: Any) -> str:
    """The palette's name for a scalar's kind."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    return "string"
