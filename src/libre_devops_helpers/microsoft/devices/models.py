"""What a device check expects, and what it found."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.entra.models import EntraDevice, EntraGroup
from libre_devops_helpers.microsoft.intune.models import ManagedDevice
from libre_devops_helpers.microsoft.xdr.models import MachineLookup

Status = Literal["met", "unmet", "error"]
Level = Literal["ok", "info", "warn"]


@dataclass(frozen=True)
class Expectations:
    """The state every device should be in. Each enabled item is one check per device."""

    in_entra: bool = True
    onboarded: bool = True
    active: bool = False
    tags: tuple[str, ...] = ()
    device_groups: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    in_intune: bool = False
    compliant: bool = False

    def __post_init__(self) -> None:
        if not self.checks:
            raise InputError(
                "nothing to check",
                hint="enable at least one of Entra, Defender, tags, device groups, groups",
            )

    @property
    def needs_entra(self) -> bool:
        return self.in_entra or bool(self.groups)

    @property
    def needs_defender(self) -> bool:
        return self.onboarded or self.active or bool(self.tags) or bool(self.device_groups)

    @property
    def needs_intune(self) -> bool:
        return self.in_intune or self.compliant

    @property
    def checks(self) -> tuple[str, ...]:
        """The check names, in the order they are reported."""
        names: list[str] = []
        if self.in_entra:
            names.append("entra")
        if self.onboarded:
            names.append("defender")
        if self.active:
            names.append("active")
        names.extend(f"tag {tag}" for tag in self.tags)
        names.extend(f"device group {group}" for group in self.device_groups)
        names.extend(f"group {group}" for group in self.groups)
        if self.in_intune:
            names.append("intune")
        if self.compliant:
            names.append("compliant")
        return tuple(names)


@dataclass(frozen=True)
class Outcome:
    """One check on one device."""

    check: str
    status: Status
    detail: str


@dataclass(frozen=True)
class DeviceReport:
    """Everything one check pass found for one device name."""

    name: str
    outcomes: tuple[Outcome, ...]
    entra: tuple[EntraDevice, ...] = ()
    defender: MachineLookup | None = None
    intune: tuple[ManagedDevice, ...] = ()

    @property
    def complete(self) -> bool:
        return all(outcome.status == "met" for outcome in self.outcomes)

    def outcome(self, check: str) -> Outcome | None:
        return next((item for item in self.outcomes if item.check == check), None)


@dataclass(frozen=True)
class CheckRun:
    """One pass over every device. ``error`` is set when the pass itself failed."""

    reports: tuple[DeviceReport, ...]
    checked_at: datetime
    expected: int
    error: str | None = None

    @property
    def complete(self) -> bool:
        return (
            self.error is None
            and len(self.reports) == self.expected
            and all(report.complete for report in self.reports)
        )

    def counts(self, checks: tuple[str, ...]) -> dict[str, int]:
        """How many devices meet each check."""
        return {
            check: sum(
                1
                for report in self.reports
                if (outcome := report.outcome(check)) is not None and outcome.status == "met"
            )
            for check in checks
        }


@dataclass(frozen=True)
class Finding:
    """One observation about a device from ``devices show``."""

    level: Level
    message: str


@dataclass(frozen=True)
class DeviceView:
    """A device across Entra, Defender and Intune, with what looks wrong about it.

    ``defender`` and ``intune`` are None when that service was not asked, or could not
    be read (a finding says which).
    """

    name: str
    entra: tuple[EntraDevice, ...]
    groups: Mapping[str, tuple[EntraGroup, ...]] = field(default_factory=dict)
    defender: MachineLookup | None = None
    intune: tuple[ManagedDevice, ...] | None = None
    findings: tuple[Finding, ...] = ()
