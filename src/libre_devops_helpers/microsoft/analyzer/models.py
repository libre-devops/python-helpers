"""What an MDE Client Analyzer run found on one device: its facts and its findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Platform = Literal["windows", "linux", "macos"]
# Worst first: the order findings are shown in, and --severity compares by.
SEVERITIES = ("error", "warning", "informational")


@dataclass(frozen=True)
class Fact:
    """One thing the analyzer recorded about the device: its OS, a version, a service's
    state. ``alert`` is the analyzer's own judgement of it, when it gave one."""

    section: str
    name: str
    value: str
    alert: str = ""


@dataclass(frozen=True)
class Finding:
    """One check's result: its id, severity (``SEVERITIES``), category, the check, what it
    found, and what to do about it (plain text, links kept)."""

    id: str
    severity: str
    category: str
    check: str
    result: str
    guidance: str = ""

    @property
    def rank(self) -> int:
        """Where the severity comes in ``SEVERITIES``: 0 is the worst."""
        return SEVERITIES.index(self.severity) if self.severity in SEVERITIES else len(SEVERITIES)


@dataclass(frozen=True)
class AnalyzerReport:
    """One analyzer result: where it came from, the platform, the device, and what it found."""

    source: str
    platform: Platform
    host: str
    facts: tuple[Fact, ...]
    findings: tuple[Finding, ...]
    analyzer_version: str = ""
    run_at: str = ""

    def fact(self, name: str) -> str:
        """The value of the first fact called ``name`` (ignoring case), or an empty string."""
        wanted = name.casefold()
        for fact in self.facts:
            if fact.name.casefold() == wanted:
                return fact.value
        return ""

    def count(self, severity: str) -> int:
        """How many findings have ``severity``."""
        return sum(1 for finding in self.findings if finding.severity == severity)
