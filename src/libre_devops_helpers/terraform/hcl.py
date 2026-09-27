"""Terraform's configuration language (HCL), as far as sorting its blocks needs: a file split
into its top-level pieces.

Not a parser. It follows strings, their ``${ }`` templates, comments and heredocs only to
know which braces open and close a block, so a brace in a description, a map default or an
``object({ })`` type never ends one early, and whatever lies between blocks is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from libre_devops_helpers.core.errors import InputError

# A block's first line: its type, its labels (quoted, or bare names), and its opening brace.
_BLOCK = re.compile(
    r'[ \t]*([A-Za-z_][A-Za-z0-9_-]*)((?:[ \t]+(?:"(?:[^"\\\n]|\\.)*"|[A-Za-z_][A-Za-z0-9_-]*))*)'
    r"[ \t]*\{"
)
_LABEL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|([A-Za-z_][A-Za-z0-9_-]*)')
_HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_-]*)[ \t]*\r?\n?\Z")
_COMMENT_STARTS = ("#", "//", "/*")
_STRING = -1  # on the nesting stack: an open string, rather than a template's brace depth


@dataclass(frozen=True)
class Piece:
    """One top-level piece of a file, as written: a block with the comments just above it
    (``kind`` its type, ``name`` its first label), or what lies between blocks."""

    text: str
    kind: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class _Line:
    text: str
    depth: int  # the blocks open at its start
    inside: str | None  # "comment", "heredoc" or "string" when it starts in one


def split(text: str) -> list[Piece]:
    """``text`` as its top-level pieces, which joined give it back as it was.

    An InputError when its braces, strings or comments do not close, which Terraform
    itself would refuse too.
    """
    lines = _Scanner().scan(text)
    pieces: list[Piece] = []
    loose: list[_Line] = []  # lines between blocks, not yet a piece
    at = 0
    while at < len(lines):
        head = _head(lines[at])
        if head is None:
            loose.append(lines[at])
            at += 1
            continue
        end = _end(lines, at)
        above = len(loose) - _comments_at_end(loose)
        if above:
            pieces.append(Piece(_joined(loose[:above])))
        pieces.append(Piece(_joined([*loose[above:], *lines[at : end + 1]]), *head))
        loose = []
        at = end + 1
    if loose:
        pieces.append(Piece(_joined(loose)))
    return pieces


def _head(line: _Line) -> tuple[str, str | None] | None:
    """The type and first label of the block ``line`` opens, or None for any other line."""
    if line.depth or line.inside:
        return None
    match = _BLOCK.match(line.text)
    if match is None:
        return None
    label = _LABEL.search(match.group(2))
    return match.group(1), (label.group(1) or label.group(2)) if label else None


def _end(lines: list[_Line], start: int) -> int:
    """The last line of the block opening on line ``start``: the one before depth is 0."""
    for at in range(start + 1, len(lines)):
        if lines[at].depth == 0 and lines[at].inside is None:
            return at - 1
    return len(lines) - 1


def _comments_at_end(lines: list[_Line]) -> int:
    """How many of the last ``lines`` are comments, with no blank line among them: those
    that document the block below them, and move with it."""
    count = 0
    for line in reversed(lines):
        if line.inside != "comment" and not line.text.lstrip().startswith(_COMMENT_STARTS):
            break
        count += 1
    return count


def _joined(lines: list[_Line]) -> str:
    return "".join(line.text for line in lines)


class _Scanner:
    """Walks the text a line at a time, keeping the depth of braces outside strings,
    templates, comments and heredocs."""

    def __init__(self) -> None:
        self.depth = 0
        self.comment = False
        self.heredoc: str | None = None
        # Open strings (_STRING) and the ${ } templates in them (their own brace depth).
        self.nesting: list[int] = []
        self.unbalanced = False

    def scan(self, text: str) -> list[_Line]:
        lines = []
        for line in text.splitlines(keepends=True):
            lines.append(_Line(line, self.depth, self._inside()))
            self._walk(line)
        if self.unbalanced or self.depth or self._inside():
            raise InputError(
                "its braces, strings or comments do not all close",
                hint="check it is valid Terraform: terraform validate",
            )
        return lines

    def _inside(self) -> str | None:
        if self.comment:
            return "comment"
        if self.heredoc is not None:
            return "heredoc"
        return "string" if self.nesting else None

    def _walk(self, line: str) -> None:
        if self.heredoc is not None:
            if line.strip() == self.heredoc:
                self.heredoc = None
            return
        at = 0
        while at < len(line):
            at = self._step(line, at)

    def _step(self, line: str, at: int) -> int:
        """Read what starts at ``at``; where the next thing starts."""
        if self.comment:
            end = line.find("*/", at)
            self.comment = end < 0
            return len(line) if end < 0 else end + 2
        if self.nesting and self.nesting[-1] == _STRING:
            return self._in_string(line, at)
        return self._in_code(line, at)

    def _in_string(self, line: str, at: int) -> int:
        if line[at] == "\\":
            return at + 2
        if line[at] == '"':
            self.nesting.pop()
            return at + 1
        if line.startswith(("$${", "%%{"), at):  # an escaped ${, which opens nothing
            return at + 3
        if line.startswith(("${", "%{"), at):
            self.nesting.append(0)
            return at + 2
        return at + 1

    def _in_code(self, line: str, at: int) -> int:
        if line.startswith(("#", "//"), at):
            return len(line)
        if line.startswith("/*", at):
            self.comment = True
            return at + 2
        heredoc = _HEREDOC.match(line, at)
        if heredoc:
            self.heredoc = heredoc.group(1)
            return len(line)
        char = line[at]
        if char == '"':
            self.nesting.append(_STRING)
        elif char == "{":
            self._open()
        elif char == "}":
            self._close()
        return at + 1

    def _open(self) -> None:
        if self.nesting:
            self.nesting[-1] += 1
        else:
            self.depth += 1

    def _close(self) -> None:
        if self.nesting:
            if self.nesting[-1] == 0:
                self.nesting.pop()  # the end of a ${ } template, back in its string
            else:
                self.nesting[-1] -= 1
            return
        self.depth -= 1
        self.unbalanced = self.unbalanced or self.depth < 0
