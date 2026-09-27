"""Message Center rollups: a month's posts summed up in one Planner task.

A month's rollup lists every post last changed in that month, laid out as the tool before
this one wrote them: the total by severity, each service's and category's count, then a
line for each post, newest change first. A task's title says which month it rolls up. A
post a rollup listed before and no longer among the month's (changed again since, or gone
from Message Center) keeps its line, so bringing a rollup up to date loses nothing.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from libre_devops_helpers.core.sorting import natural_key
from libre_devops_helpers.microsoft.news.models import Message

# "Message Center rollup: 2026-07 (8 messages)", and the month as the first group; the tool
# before this one also wrote "month 2026-07".
ROLLUP_TITLE = re.compile(r"^Message Center rollup: (?:month )?(\d{4}-\d{2})\b", re.IGNORECASE)
# Planner does not say how long a description can be; this is well within what it takes.
DESCRIPTION_LIMIT = 25_000
_LISTED = re.compile(r"^- (MC[0-9]+) ", re.MULTILINE | re.IGNORECASE)
_SEVERITIES = ("critical", "high", "normal")
_EARLIER = (
    "Listed before, and no longer among the month's posts: changed again since, or gone "
    "from Message Center."
)


@dataclass(frozen=True)
class Rollup:
    """One month's posts (``2026-09``), as a Planner task's title and description."""

    month: str
    messages: tuple[Message, ...]
    earlier: tuple[str, ...] = ()  # lines for posts listed before, as they were written

    def keeping(self, description: str) -> Rollup:
        """This rollup, keeping the line ``description`` (what it said before) has for each
        post no longer among the month's."""
        ids = self.ids
        kept: dict[str, str] = {}
        for line in description.splitlines():
            match = _LISTED.match(line)
            if match and match.group(1).upper() not in ids:
                kept.setdefault(match.group(1).upper(), line.strip())
        return Rollup(self.month, self.messages, tuple(kept.values()))

    @property
    def title(self) -> str:
        """``Message Center rollup: 2026-09 (12 messages)``."""
        count = len(self.messages)
        return f"Message Center rollup: {self.month} ({count} message{'' if count == 1 else 's'})"

    @property
    def ids(self) -> frozenset[str]:
        """The ids of the posts it rolls up."""
        return frozenset(message.id.upper() for message in self.messages)

    @property
    def description(self) -> str:
        """The summary: the counts, then a line for each post, cut to fit Planner."""
        head = [
            f"# Message Center summary ({self.month})",
            "",
            f"Total: {len(self.messages)} messages ({_severities(self.messages)})",
            "",
            "## By service",
            *_counts(service for message in self.messages for service in message.services),
            "",
            "## By category",
            *_counts(message.category or "none" for message in self.messages),
            "",
            "## Messages",
        ]
        lines = [_line(message) for message in self.messages]
        if self.earlier:
            lines += ["", "## Listed before", _EARLIER, *self.earlier]
        return _fit("\n".join(head), lines)


def listed(description: str) -> frozenset[str]:
    """The ids of the posts a rollup's description lists."""
    return frozenset(found.upper() for found in _LISTED.findall(description))


def months(start: datetime, end: datetime) -> list[tuple[str, datetime, datetime]]:
    """Each month from the one ``start`` is in to the one just before ``end``: its name
    (``2026-09``), its first moment and the next month's, in UTC."""
    first = start.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    found: list[tuple[str, datetime, datetime]] = []
    while first < end and start < end:
        after = datetime(first.year + first.month // 12, first.month % 12 + 1, 1, tzinfo=UTC)
        found.append((f"{first:%Y-%m}", first, after))
        first = after
    return found


def _severities(messages: Sequence[Message]) -> str:
    """``0 critical, 1 high, 11 normal``, and any other severity Graph gives after them."""
    counts = Counter(message.severity.casefold() or "normal" for message in messages)
    names = [*_SEVERITIES, *(name for name in counts if name not in _SEVERITIES)]
    return ", ".join(f"{counts[name]} {name}" for name in names)


def _counts(values: Iterable[str]) -> list[str]:
    """A ``- name: count`` line for each value, the commonest first."""
    counts = Counter(values)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], natural_key(item[0])))
    return [f"- {name}: {count}" for name, count in ranked]


def _line(message: Message) -> str:
    """``- MC1183010 2026-07-20 [Microsoft Teams] its title``, on one line whatever the
    title holds, so no title can pass for another post's line."""
    day = f"{message.updated.astimezone(UTC):%Y-%m-%d}" if message.updated else "-"
    services = f" [{', '.join(message.services)}]" if message.services else ""
    return f"- {message.id} {day}{services} {' '.join(message.title.split())}"


def _fit(head: str, lines: Sequence[str]) -> str:
    """``head`` and as many of ``lines`` as fit Planner, then how many did not."""
    room = DESCRIPTION_LIMIT - len(head) - 100  # for the line saying what is left out
    kept: list[str] = []
    for line in lines:
        room -= len(line) + 1
        if room < 0:
            break
        kept.append(line)
    if len(kept) < len(lines):
        left = len(listed("\n".join(lines[len(kept) :])))
        kept.append(f"- and {left} more, too many for one task")
    return "\n".join([head, *kept])
