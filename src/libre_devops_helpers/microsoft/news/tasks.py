"""How a Planner task raised for a Message Center post reads: its title and its notes.

Two layouts. ``sync``, the default, is the one Microsoft's own Message Center sync to
Planner writes, so a plan can hold both its tasks and these and they look alike:
``[Microsoft Teams] <title> [MC1183010]``, the notes starting with the post's id,
published date, category and tags. ``short`` is ``MC1183010: <title>``, as the tool before
this one wrote them. Both notes go on with the post's link and its text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from libre_devops_helpers.core.markdown import html_to_markdown
from libre_devops_helpers.microsoft.news.models import Message

# A task's notes hold the post's text, up to this much of it.
TEXT_LIMIT = 6000
# Room a title keeps for the post's own title before its services are left out.
_TITLE_ROOM = 40


class Layout(StrEnum):
    """How a task for a post reads."""

    SYNC = "sync"
    SHORT = "short"


def task_title(message: Message, layout: Layout, *, limit: int) -> str:
    """The task's title, no longer than ``limit``: the post's title is what is cut, so the
    id, which says the task is the post's, is always there."""
    if layout is Layout.SHORT:
        head, tail = f"{message.id}: ", ""
    else:
        head = f"[{', '.join(message.services)}] " if message.services else ""
        tail = f" [{message.id}]"
        if limit - len(head) - len(tail) < _TITLE_ROOM:
            head = ""  # so many services that the title would have no room
    title = " ".join(message.title.split())
    room = limit - len(head) - len(tail)
    if len(title) > room:
        kept = title[: max(room - 3, 0)]
        if " " in kept:
            kept = kept.rsplit(" ", 1)[0]  # at a word's end, not in the middle of one
        title = kept.rstrip() + "..."
    return f"{head}{title}{tail}"


def task_notes(message: Message, layout: Layout) -> str:
    """The task's notes: in the sync layout, first the post's id, published date, category
    and tags, as the sync lists them; then its link in the admin centre, and its text as
    Markdown, cut to TEXT_LIMIT."""
    lines = [*_details(message), ""] if layout is Layout.SYNC else []
    lines += [message.url, "", _text(message)]
    return "\n".join(lines).strip()


def _details(message: Message) -> list[str]:
    found = [f"Message ID: {message.id}"]
    if message.starts is not None:
        found.append(f"Published date: {_month_first(message.starts)}")
    if message.category:
        label = message.category_label
        found.append(f"Category: {label[:1].upper()}{label[1:]}")
    if message.tags:
        found.append(f"Tags: {', '.join(message.tags)}")
    return found


def _month_first(moment: datetime) -> str:
    """``9/21/2026``: the day in UTC, month first, as the sync writes it."""
    day = moment.astimezone(UTC)
    return f"{day.month}/{day.day}/{day.year}"


def _text(message: Message) -> str:
    text = html_to_markdown(message.body_html).strip() if message.body_html else ""
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT].rstrip() + "\n\n(more in the admin centre)"
    return text
