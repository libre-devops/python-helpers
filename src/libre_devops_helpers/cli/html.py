"""The page ``-o html`` writes: a command's table as one self-contained, styled HTML file.

Everything is in the file: no font, style or script is fetched, so it opens offline, from
an email or behind a proxy that blocks every CDN. Its content security policy lets the
page run only its own style and script (by hash) and load nothing at all, and every
value in it is escaped. render.py loads this module only when ``-o html`` is asked for,
so no other command pays for it.
"""

from __future__ import annotations

import base64
import hashlib
import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand

Cell = str | tuple[str, str | None]

# The table's colours, as the page's styles name them.
_STATUS = {"green": "ok", "yellow": "warn", "red": "err", "bright_black": "muted"}

_STYLE = """\
:root{--bg:#f6f7f9;--card:#fff;--fg:#1c1f24;--muted:#5f6b7a;--line:#e3e6eb;--ok:#1a7f37;
--warn:#9a6700;--err:#cf222e;--okbg:#dafbe1;--warnbg:#fff8c5;--errbg:#ffebe9}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e6e8eb;
--muted:#9aa4b2;--line:#2a2f3a;--ok:#3fb950;--warn:#d29922;--err:#f85149;--okbg:#12261a;
--warnbg:#2b2211;--errbg:#2d1416}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif}
header{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 65%,#000));
color:#fff;padding:22px 28px}
header .brand{font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85}
header h1{margin:4px 0 8px;font-size:22px;font-weight:600}
header code{background:rgba(255,255,255,.14);padding:2px 8px;border-radius:6px;
font-size:12.5px;word-break:break-all}
main{padding:20px 28px 32px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;
min-width:120px}
.card b{display:block;font-size:22px;line-height:1.3}
.card span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.card.ok b{color:var(--ok)}.card.warn b{color:var(--warn)}.card.err b{color:var(--err)}
.notes{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:10px;padding:8px 16px;margin-bottom:16px;color:var(--muted)}
.notes p{margin:4px 0}.notes .warning{color:var(--warn)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;
margin-bottom:20px}
.toolbar{display:flex;gap:10px;align-items:center;padding:10px 12px;
border-bottom:1px solid var(--line)}
.toolbar input{flex:1;max-width:360px;padding:7px 10px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg);font:inherit}
.toolbar button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--fg);font:inherit;cursor:pointer}
.toolbar .count{margin-left:auto;color:var(--muted);font-size:12px}
.scroll{overflow:auto;max-height:75vh}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:var(--card);text-align:left;font-size:11px;
text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:9px 12px;
border-bottom:2px solid var(--line);cursor:pointer;white-space:nowrap;user-select:none}
th[aria-sort=ascending]::after{content:" \\25B2"}th[aria-sort=descending]::after{content:" \\25BC"}
td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top;white-space:pre-line}
td:first-child,.pill{white-space:nowrap}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--line) 30%,transparent)}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 9%,transparent)}
tr.err td:first-child{box-shadow:inset 3px 0 var(--err)}
tr.warn td:first-child{box-shadow:inset 3px 0 var(--warn)}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:500}
.pill.ok{background:var(--okbg);color:var(--ok)}.pill.warn{background:var(--warnbg);color:var(--warn)}
.pill.err{background:var(--errbg);color:var(--err)}.muted{color:var(--muted)}
footer{color:var(--muted);font-size:12px;padding:0 28px 24px}footer a{color:inherit}
@media print{.toolbar{display:none}.scroll{max-height:none;overflow:visible}
header{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
"""

_SCRIPT = """\
(() => {
  const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: "base"});
  const quote = (value) => /[",\\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  for (const panel of document.querySelectorAll(".panel")) {
    const table = panel.querySelector("table");
    const body = table.tBodies[0];
    const rows = [...body.rows];
    const filter = panel.querySelector("input");
    const count = panel.querySelector(".count");
    const copy = panel.querySelector("button");
    const heads = [...table.tHead.rows[0].cells];
    const shown = () => rows.filter((row) => !row.hidden);
    const counted = () => { count.textContent = `${shown().length} of ${rows.length} rows`; };
    filter.addEventListener("input", () => {
      const wanted = filter.value.trim().toLowerCase();
      for (const row of rows) {
        row.hidden = wanted !== "" && !row.textContent.toLowerCase().includes(wanted);
      }
      counted();
    });
    heads.forEach((head, index) => head.addEventListener("click", () => {
      const order = head.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
      heads.forEach((other) => other.removeAttribute("aria-sort"));
      head.setAttribute("aria-sort", order);
      const sign = order === "ascending" ? 1 : -1;
      const text = (row) => row.cells[index].textContent;
      rows.sort((a, b) => sign * collator.compare(text(a), text(b)));
      body.append(...rows);
    }));
    copy.addEventListener("click", () => {
      const lines = [heads.map((head) => quote(head.textContent))];
      for (const row of shown()) lines.push([...row.cells].map((cell) => quote(cell.textContent)));
      const text = lines.map((line) => line.join(",")).join("\\n");
      const done = () => {
        copy.textContent = "Copied";
        setTimeout(() => { copy.textContent = "Copy as CSV"; }, 1500);
      };
      if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done); return; }
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      done();
    });
    counted();
  }
})();
"""


@dataclass(frozen=True)
class Table:
    """One table a command wrote: its headers, and its rows as the terminal shows them."""

    headers: Sequence[str]
    rows: Sequence[Sequence[Cell]]


def page(
    *,
    heading: str,
    command: str,
    tables: Sequence[Table],
    notes: Sequence[tuple[str, str]],
    generated: datetime,
) -> str:
    """The whole page: ``notes`` are (kind, text), kind "note" or "warning"."""
    style = f":root{{--accent:{_accent()}}}\n{_STYLE}"
    policy = (
        f"default-src 'none'; style-src '{_digest(style)}'; script-src '{_digest(_SCRIPT)}'; "
        "img-src data:; base-uri 'none'; form-action 'none'"
    )
    title = f"{heading} | {brand.DISPLAY_NAME}"
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{policy}">',
        f"<title>{_e(title)}</title><style>{style}</style></head><body>",
        f'<header><div class="brand">{_e(brand.DISPLAY_NAME)}</div><h1>{_e(heading)}</h1>',
        f"<code>{_e(command)}</code></header><main>",
        _cards(tables),
        _notes(notes),
        *(_panel(table) for table in tables),
        "</main>",
        f"<footer>Written {_e(generated.strftime('%Y-%m-%d %H:%M %Z').strip())} by "
        f"{_e(brand.COMMAND)} {_e(__version__)}, "
        f'<a href="{_e(brand.REPOSITORY)}">{_e(brand.REPOSITORY)}</a></footer>',
        f"<script>{_SCRIPT}</script></body></html>",
    ]
    return "\n".join(part for part in parts if part) + "\n"


def row_status(row: Sequence[Cell]) -> str:
    """The worst colour a row carries: ``err``, ``warn``, ``ok``, or "" for none."""
    found = {_STATUS.get(cell[1] or "") for cell in row if isinstance(cell, tuple)}
    for status in ("err", "warn", "ok"):
        if status in found:
            return status
    return ""


def _cards(tables: Sequence[Table]) -> str:
    statuses = [row_status(row) for table in tables for row in table.rows]
    cards = [("", len(statuses), "rows")]
    for status, label in (("ok", "ok"), ("warn", "attention"), ("err", "errors")):
        if statuses.count(status):
            cards.append((status, statuses.count(status), label))
    return (
        '<div class="cards">'
        + "".join(
            f'<div class="card {status}"><b>{count}</b><span>{label}</span></div>'
            for status, count, label in cards
        )
        + "</div>"
    )


def _notes(notes: Sequence[tuple[str, str]]) -> str:
    if not notes:
        return ""
    lines = "".join(f'<p class="{_e(kind)}">{_e(text)}</p>' for kind, text in notes)
    return f'<div class="notes">{lines}</div>'


def _panel(table: Table) -> str:
    head = "".join(f"<th>{_e(header)}</th>" for header in table.headers)
    body = "".join(_row(row) for row in table.rows)
    return (
        '<section class="panel"><div class="toolbar">'
        '<input type="search" placeholder="Filter rows" aria-label="Filter rows">'
        '<button type="button">Copy as CSV</button><span class="count"></span></div>'
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody>'
        "</table></div></section>"
    )


def _row(row: Sequence[Cell]) -> str:
    status = row_status(row)
    kind = f' class="{status}"' if status in {"err", "warn"} else ""
    return f"<tr{kind}>" + "".join(f"<td>{_cell(cell)}</td>" for cell in row) + "</tr>"


def _cell(cell: Cell) -> str:
    if not isinstance(cell, tuple):
        return _e(cell)
    text, colour = cell
    status = _STATUS.get(colour or "")
    if status == "muted":
        return f'<span class="muted">{_e(text)}</span>'
    if status and text:
        return f'<span class="pill {status}">{_e(text)}</span>'
    return _e(text)


def _accent() -> str:
    # A colour the page puts in its CSS as it is, so only a #RRGGBB one is let in.
    value = brand.ACCENT.strip()
    valid = len(value) == 7 and value.startswith("#")
    if valid and all(char in "0123456789abcdefABCDEF" for char in value[1:]):
        return value
    return "#1E3A8A"


def _digest(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()


def _e(text: str) -> str:
    return html.escape(str(text), quote=True)
