"""A small picture for a terminal: a logo in its own colours, two pixels to a character.

A picture is plain text, so it can live in code and be reviewed like it:

    # a palette: a letter, its colour, and the character the plain version draws it with
    p #1E3A8A :
    r #F97316 #
    ---
    ..pppp..
    .pprrpp.
    .pprrpp.
    ..pppp..

Each row is a row of pixels, the same width, each pixel a palette letter; ``.`` (or a
space) is no pixel at all. In colour, each line of the terminal draws two rows with half
blocks, the upper one in the foreground and the lower one behind it, which makes each
pixel about square. Without colour, or where the output cannot show the blocks, each line
draws the upper pixel's character (else the lower's), so the shape survives in plain
ASCII: in a log, a pipe, or an old console.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from libre_devops_helpers.core import colour

_BLANK = frozenset(". ")
_ENTRY = re.compile(r"([A-Za-z0-9])\s+(#[0-9A-Fa-f]{6})(?:\s+(\S))?")
# What a line of the coloured picture is drawn with: upper half, lower half, both.
_UPPER, _LOWER, _FULL = "▀", "▄", "█"


@dataclass(frozen=True)
class Picture:
    """A picture: its palette (a letter's colour and plain character) and its pixel rows."""

    colours: dict[str, str]
    characters: dict[str, str]
    rows: tuple[str, ...]

    @property
    def width(self) -> int:
        """How many characters wide it is drawn."""
        return len(self.rows[0]) if self.rows else 0

    def lines(self, *, coloured: bool) -> list[str]:
        """The lines to print: half blocks in colour, or plain characters."""
        drawn = []
        for index in range(0, len(self.rows), 2):
            upper = self.rows[index]
            lower = self.rows[index + 1] if index + 1 < len(self.rows) else ""
            drawn.append(self._coloured(upper, lower) if coloured else self._plain(upper, lower))
        return drawn

    def _plain(self, upper: str, lower: str) -> str:
        cells = []
        for column, top in enumerate(upper):
            bottom = lower[column] if lower else "."
            pixel = top if top not in _BLANK else bottom
            cells.append(" " if pixel in _BLANK else self.characters[pixel])
        return "".join(cells).rstrip()

    def _coloured(self, upper: str, lower: str) -> str:
        cells = []
        for column, top in enumerate(upper):
            bottom = lower[column] if lower else "."
            cells.append(self._cell(top, bottom))
        return "".join(cells).rstrip()

    def _cell(self, top: str, bottom: str) -> str:
        if top in _BLANK and bottom in _BLANK:
            return " "
        if bottom in _BLANK:
            return colour.style(_UPPER, self.colours[top])
        if top in _BLANK:
            return colour.style(_LOWER, self.colours[bottom])
        if top == bottom:
            return colour.style(_FULL, self.colours[top])
        return colour.style(_UPPER, self.colours[top], bg=self.colours[bottom])


def parse(text: str) -> Picture:
    """``text`` (a palette, ``---``, then rows) as a Picture; ValueError saying what is
    wrong with it, since a picture is part of the code, checked by its tests."""
    head, separator, body = text.partition("\n---\n")
    if not separator:
        raise ValueError("a picture needs a palette, a line of ---, then its rows")
    colours: dict[str, str] = {}
    characters: dict[str, str] = {}
    for line in head.splitlines():
        line = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        if not line.strip():
            continue
        entry = _ENTRY.fullmatch(line.strip())
        if entry is None:
            raise ValueError(f"not a palette entry (LETTER #RRGGBB [CHARACTER]): {line!r}")
        letter, hex_colour, character = entry.groups()
        colours[letter] = hex_colour.upper()
        characters[letter] = character or letter
    rows = tuple(row for row in body.splitlines() if row.strip())
    _check_rows(rows, colours)
    return Picture(colours, characters, rows)


def _check_rows(rows: tuple[str, ...], colours: dict[str, str]) -> None:
    if not rows:
        raise ValueError("a picture needs at least one row of pixels")
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise ValueError(f"every row of a picture must be as wide: found {sorted(widths)}")
    unknown = sorted({pixel for row in rows for pixel in row} - set(colours) - _BLANK)
    if unknown:
        raise ValueError(f"pixels not in the palette: {', '.join(unknown)}")
