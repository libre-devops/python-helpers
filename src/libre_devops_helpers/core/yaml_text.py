"""JSON-shaped data as YAML, with the standard library alone.

Only what JSON can hold is written (objects, arrays, strings, numbers, booleans, null),
in block style. A string is left plain only when no YAML reader could take it for
anything else: ``yes``, ``no``, ``null``, ``1.0``, ``2026-09-24``, ``@odata.context`` and
``a: b`` are all quoted, as JSON strings, which YAML reads the same way. A multi-line
string becomes a ``|`` block. There is no parser: reading YAML is not needed here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

# kind ("key", "string", "number", "bool", "null", "punct") and text -> text to write.
Paint = Callable[[str, str], str]

# Plain only when it starts with a letter or underscore and holds nothing YAML reads
# specially; single spaces between words are fine.
_PLAIN = re.compile(r"[A-Za-z_][\w.\-/+@]*(?: [\w.\-/+@]+)*")
# Words YAML 1.1 or 1.2 readers take for booleans or null, in any case.
_WORDS = frozenset(
    {"true", "false", "yes", "no", "on", "off", "y", "n", "null", "none", "nan", "inf"}
)
# Characters YAML will not take as they are inside a quoted string: C1 controls (U+0085
# is a line break to YAML), the Unicode line and paragraph separators, and non-characters.
_UNPRINTABLE = re.compile(r"[\x7f-\x9f\u2028\u2029\ufeff\ufffe\uffff\ud800-\udfff]")
# Characters that make a string unsafe for a literal block: controls other than tab.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u0085\u2028\u2029\ufeff]")


def dumps(data: Any, *, indent: int = 2, paint: Paint | None = None) -> str:
    """``data`` (as ``json.loads`` gives it) as a YAML document, ending in a newline.

    The newline matters: a ``|`` block last in the document keeps its own final line
    break only when the document ends with one.
    """
    painter = paint or (lambda _kind, text: text)
    return "\n".join(_node(data, 0, max(indent, 1), painter)) + "\n"


def _node(value: Any, level: int, indent: int, paint: Paint) -> list[str]:
    """The lines for ``value`` standing alone, at ``level`` spaces."""
    pad = " " * level
    if isinstance(value, dict) and value:
        lines = []
        for key, item in value.items():
            head = f"{pad}{paint('key', _string(str(key)))}{paint('punct', ':')}"
            lines.extend(_entry(head, item, level, indent, paint))
        return lines
    if isinstance(value, list) and value:
        lines = []
        for item in value:
            lines.extend(_item(item, level, indent, paint))
        return lines
    first, *rest = _scalar(value, level, indent, paint)
    return [pad + first, *_indented(rest, level + indent)]


def _entry(head: str, value: Any, level: int, indent: int, paint: Paint) -> list[str]:
    """``key:`` followed by its value: on the same line, or nested below it."""
    if _nests(value):
        return [head, *_node(value, level + indent, indent, paint)]
    first, *rest = _scalar(value, level + indent, indent, paint)
    return [f"{head} {first}", *_indented(rest, level + indent)]


def _item(value: Any, level: int, indent: int, paint: Paint) -> list[str]:
    """``- `` followed by an array item; a nested object or array starts on the same line."""
    dash = " " * level + paint("punct", "-")
    if _nests(value):
        inner = _node(value, level + 2, indent, paint)
        return [dash + " " + inner[0].lstrip(), *inner[1:]]
    first, *rest = _scalar(value, level + 2, indent, paint)
    return [f"{dash} {first}", *_indented(rest, level + 2)]


def _indented(lines: list[str], level: int) -> list[str]:
    """A block's lines at ``level``; blank ones stay empty, with no trailing spaces."""
    return [" " * level + line if line else "" for line in lines]


def _nests(value: Any) -> bool:
    return isinstance(value, dict | list) and bool(value)


def _scalar(value: Any, level: int, indent: int, paint: Paint) -> list[str]:
    """A scalar's lines: one, or a ``|`` header and a block, each without the indent."""
    if value is None:
        return [paint("null", "null")]
    if isinstance(value, bool):
        return [paint("bool", "true" if value else "false")]
    if isinstance(value, float):
        return [paint("number", _float(value))]
    if isinstance(value, int):
        return [paint("number", json.dumps(value))]
    if isinstance(value, dict):
        return [paint("punct", "{}")]
    if isinstance(value, list):
        return [paint("punct", "[]")]
    text = str(value)
    block = _block(text)
    if block is not None:
        return [paint("punct", block[0]), *(paint("string", line) for line in block[1:])]
    return [paint("string", _string(text))]


def _float(value: float) -> str:
    """A float every YAML reader takes as one: YAML 1.1 wants a point, so 1e-07 is 1.0e-07."""
    text = json.dumps(value)
    mantissa, marker, exponent = text.partition("e")
    if marker and "." not in mantissa:
        return f"{mantissa}.0e{exponent}"
    return text


def _string(text: str) -> str:
    """``text`` plain when that reads back as the same string, else JSON-quoted."""
    # fullmatch, not match with $: in Python, $ also matches before a final newline.
    if _PLAIN.fullmatch(text) and text.casefold() not in _WORDS:
        return text
    quoted = json.dumps(text, ensure_ascii=False)
    return _UNPRINTABLE.sub(lambda found: f"\\u{ord(found.group()):04x}", quoted)


def _block(text: str) -> list[str] | None:
    """A multi-line string as a literal block (``|``), or None when it cannot be one.

    The lines come back unindented; the caller indents them. A block must not start with
    a space (the reader would take that as the indent), and holds no control characters.
    """
    if "\n" not in text or _CONTROL.search(text) or text.startswith((" ", "\n")):
        return None
    body = text.rstrip("\n")
    trailing = len(text) - len(body)
    chomp = {0: "|-", 1: "|"}.get(trailing, "|+")
    lines = body.split("\n") + [""] * (trailing - 1 if trailing > 1 else 0)
    if any(line.endswith((" ", "\t")) for line in lines):
        return None  # trailing spaces would be invisible, so quote it instead
    return [chomp, *lines]
