"""HTML as Markdown: a page or a description, readable in a terminal and in a file.

It covers what documents are made of: headings, paragraphs, emphasis, links, lists
(nested), tables, quotes and code, and Confluence's storage format beside them (its code
macro, its tasks, its links to pages), whose settings are left out. Anything else keeps
its text. Only the standard library's parser is used, and nothing is fetched.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCKS = {"p", "div", "section", "article", "header", "footer", "ac:layout-cell"}
_HEADINGS = {f"h{level}": level for level in range(1, 7)}
_EMPHASIS = {"strong": "**", "b": "**", "em": "_", "i": "_", "code": "`", "s": "~~", "del": "~~"}
# Confluence's storage format: tags whose content is a setting, not text.
_HIDDEN = {"ac:parameter", "script", "style", "ri:attachment", "ac:emoticon"}


def html_to_markdown(html: str) -> str:
    """``html`` as Markdown text."""
    converter = _Converter()
    converter.feed(html)
    converter.close()
    return converter.markdown()


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Text is written into the innermost buffer: a link's or a table cell's, or the page.
        self.buffers: list[list[str]] = [[]]
        self.lists: list[list[int | str]] = []  # each open list: [kind, number]
        self.links: list[str] = []
        self.rows: list[list[str]] = []
        self.hidden = 0
        self.pre = 0
        self.code_macro = False

    # Parsing ---------------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self.hidden += 1
        elif tag in _HEADINGS:
            self._block("#" * _HEADINGS[tag] + " ")
        elif tag in _EMPHASIS:
            self._write(_EMPHASIS[tag])
        else:
            self._start_structure(tag, dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif tag in _HEADINGS or tag in _BLOCKS or tag == "blockquote":
            self._block("")
        elif tag in _EMPHASIS:
            self._write(_EMPHASIS[tag])
        else:
            self._end_structure(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._write("  \n" if not self.rows else " ")
        elif tag == "hr":
            self._block("---")
            self._block("")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            self._write(f"[{alt}]" if alt else "")
        else:
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        self._write(data if self.pre else re.sub(r"\s+", " ", data))

    def unknown_decl(self, data: str) -> None:
        # CDATA: Confluence keeps a code block's text in one.
        if data.startswith("CDATA[") and not self.hidden:
            self._write(data[len("CDATA[") :])

    # Structure -------------------------------------------------------------------------

    def _start_structure(self, tag: str, attrs: dict[str, str | None]) -> None:
        if tag in _BLOCKS:
            self._block("")
        elif tag in {"ul", "ol", "ac:task-list"}:
            self.lists.append(["ol" if tag == "ol" else "ul", 0])
        elif tag in {"li", "ac:task"}:
            self._item("[ ] " if tag == "ac:task" else "")
        elif tag == "blockquote":
            self._block("> ")
        elif tag == "pre" or (tag == "ac:plain-text-body" and self.code_macro):
            self.pre += 1
            self._block("```\n")
        elif tag == "ac:structured-macro":
            self.code_macro = attrs.get("ac:name") in {"code", "noformat"}
        elif tag == "a":
            self.links.append(attrs.get("href") or "")
            self.buffers.append([])
        else:
            self._start_table(tag)

    def _end_structure(self, tag: str) -> None:
        if tag in {"ul", "ol", "ac:task-list"} and self.lists:
            self.lists.pop()
            if not self.lists:
                self._block("")
        elif tag == "pre" or (tag == "ac:plain-text-body" and self.code_macro):
            self.pre = max(0, self.pre - 1)
            self._write("\n```")
            self._block("")
        elif tag == "ac:structured-macro":
            self.code_macro = False
        elif tag == "a" and self.links:
            text = "".join(self.buffers.pop()).strip()
            href = self.links.pop()
            self._write(f"[{text}]({href})" if href and text and href != text else text or href)
        else:
            self._end_table(tag)

    def _start_table(self, tag: str) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag in {"td", "th"}:
            self.buffers.append([])

    def _end_table(self, tag: str) -> None:
        if tag in {"td", "th"} and len(self.buffers) > 1 and self.rows:
            cell = "".join(self.buffers.pop()).strip().replace("|", "\\|")
            self.rows[-1].append(cell)
        elif tag == "table" and self.rows:
            self._block(_table(self.rows))
            self._block("")
            self.rows = []

    # Writing ---------------------------------------------------------------------------

    def _write(self, text: str) -> None:
        self.buffers[-1].append(text)

    def _block(self, start: str) -> None:
        # A table cell is one line, and a list item's paragraphs run on after its bullet.
        in_cell = bool(self.rows) and len(self.buffers) > 1
        if in_cell or (self.lists and not start.startswith("```")):
            self._write(" ")
            return
        self._write("\n\n" + start)

    def _item(self, marker: str) -> None:
        if not self.lists:
            self.lists.append(["ul", 0])
        kind = self.lists[-1]
        kind[1] = int(kind[1]) + 1
        bullet = f"{kind[1]}." if kind[0] == "ol" else "-"
        if self.rows and len(self.buffers) > 1:  # in a table cell, the list runs on
            self._write(f" {bullet} {marker}")
            return
        self._write("\n" + "  " * (len(self.lists) - 1) + f"{bullet} {marker}")

    def markdown(self) -> str:
        while len(self.buffers) > 1:  # an unclosed link or cell keeps its text
            text = "".join(self.buffers.pop())
            self._write(text)
        lines, fenced = [], False
        for line in "".join(self.buffers[0]).split("\n"):
            if line.startswith("```"):
                fenced = not fenced
            elif not fenced:
                # One space between words, keeping a hard break's two at the end.
                hard = line.endswith("  ") and line.strip()
                line = re.sub(r"(?<=\S) {2,}(?=\S)", " ", line.rstrip()) + ("  " if hard else "")
            lines.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows if row]
    lines = ["| " + " | ".join(padded[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)
