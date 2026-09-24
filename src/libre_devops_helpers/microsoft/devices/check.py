"""Check a list of devices against expectations, once (fast) or until done (watch).

Speed comes from three things. Lookups for different devices run in parallel. Each
expected group's members are fetched once per pass rather than once per device. And a
watch rechecks only the devices not yet complete, unless asked to recheck them all.

A rejected token or a missing permission (HTTP 401 or 403) ends the check, since every
device would fail the same way. Anything else that fails for one device is recorded
as an error for that device, and a watch simply tries again next pass.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TypeVar

from libre_devops_helpers.core.auth import utc_now
from libre_devops_helpers.core.errors import ApiError, LdoError, ReauthRequired
from libre_devops_helpers.core.poll import PollLimits, PollOutcome, poll
from libre_devops_helpers.microsoft.devices.models import (
    CheckRun,
    DeviceReport,
    Expectations,
    Outcome,
)
from libre_devops_helpers.microsoft.entra.client import EntraClient
from libre_devops_helpers.microsoft.entra.models import EntraDevice
from libre_devops_helpers.microsoft.intune.client import IntuneClient
from libre_devops_helpers.microsoft.intune.models import ManagedDevice
from libre_devops_helpers.microsoft.xdr.client import XdrClient
from libre_devops_helpers.microsoft.xdr.models import MachineLookup

_FATAL = frozenset({401, 403})

T = TypeVar("T")


class DeviceChecker:
    """Checks devices against ``Expectations`` using whichever clients they need."""

    def __init__(
        self,
        *,
        entra: EntraClient | None = None,
        xdr: XdrClient | None = None,
        intune: IntuneClient | None = None,
        workers: int = 8,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if workers < 1:
            raise LdoError("workers must be at least 1")
        self._entra = entra
        self._xdr = xdr
        self._intune = intune
        self._workers = workers
        self._clock = clock

    def check(self, names: Sequence[str], expectations: Expectations) -> CheckRun:
        """One pass over ``names``, in order."""
        self._require_clients(expectations)
        self._prepare(expectations)
        members = self._group_members(expectations.groups)
        if not names:
            return CheckRun((), self._clock(), 0)
        try:
            reports = self._check_all(names, expectations, members)
        except ReauthRequired:
            # A sign-in lapsed mid-pass, in a worker, which must not stop to ask anyone.
            # Ask here on the calling thread (this raises again if nobody can sign in),
            # then run the pass again.
            self._prepare(expectations)
            reports = self._check_all(names, expectations, members)
        return CheckRun(tuple(reports), self._clock(), len(names))

    def _prepare(self, expectations: Expectations) -> None:
        """Get each service's token on this thread before the workers need it.

        A token is normally cached already, so this is cheap; when a sign-in has lapsed,
        it is where a credential that can ask someone to sign in again gets to ask.
        """
        for needed, client in (
            (expectations.needs_entra or expectations.groups, self._entra),
            (expectations.needs_defender, self._xdr),
            (expectations.needs_intune, self._intune),
        ):
            if needed and client is not None:
                client.api.ensure_token()

    def _check_all(
        self,
        names: Sequence[str],
        expectations: Expectations,
        members: Mapping[str, frozenset[str]],
    ) -> list[DeviceReport]:
        with ThreadPoolExecutor(max_workers=min(self._workers, len(names))) as pool:
            return list(pool.map(lambda name: self._check_one(name, expectations, members), names))

    def _require_clients(self, expectations: Expectations) -> None:
        missing = [
            service
            for service, needed, client in (
                ("Entra", expectations.needs_entra, self._entra),
                ("Defender", expectations.needs_defender, self._xdr),
                ("Intune", expectations.needs_intune, self._intune),
            )
            if needed and client is None
        ]
        if missing:
            raise LdoError(f"these checks need a client for {', '.join(missing)}")

    def _group_members(self, groups: Sequence[str]) -> dict[str, frozenset[str]]:
        if not groups or self._entra is None:
            return {}
        entra = self._entra
        members: dict[str, frozenset[str]] = {}
        for ref in groups:
            group = entra.get_group(ref)
            members[ref] = frozenset(device.id for device in entra.group_devices(group))
        return members

    def _check_one(
        self, name: str, expectations: Expectations, members: Mapping[str, frozenset[str]]
    ) -> DeviceReport:
        errors: dict[str, str] = {}
        entra_devices: tuple[EntraDevice, ...] = ()
        lookup: MachineLookup | None = None
        managed: tuple[ManagedDevice, ...] = ()
        if expectations.needs_entra and self._entra is not None:
            entra = self._entra
            entra_devices = _guarded(errors, "entra", lambda: tuple(entra.find_devices(name)), ())
        if expectations.needs_defender and self._xdr is not None:
            xdr = self._xdr
            lookup = _guarded(errors, "defender", lambda: xdr.find_machine(name), None)
        if expectations.needs_intune and self._intune is not None:
            intune = self._intune
            managed = _guarded(errors, "intune", lambda: tuple(intune.find_devices(name)), ())

        outcomes: list[Outcome] = []
        if expectations.in_entra:
            outcomes.append(_entra_outcome(entra_devices, errors.get("entra")))
        machine = lookup.machine if lookup is not None else None
        defender_error = errors.get("defender")
        if expectations.onboarded:
            if defender_error:
                outcomes.append(Outcome("defender", "error", defender_error))
            elif machine is None:
                outcomes.append(Outcome("defender", "unmet", "no Defender record"))
            elif machine.onboarding_status == "Onboarded":
                outcomes.append(Outcome("defender", "met", f"onboarded, {machine.health_status}"))
            else:
                outcomes.append(
                    Outcome("defender", "unmet", machine.onboarding_status or "not onboarded")
                )
        if expectations.active:
            if defender_error:
                outcomes.append(Outcome("active", "error", defender_error))
            elif machine is None:
                outcomes.append(Outcome("active", "unmet", "no Defender record"))
            elif machine.health_status == "Active":
                outcomes.append(Outcome("active", "met", "Active"))
            else:
                outcomes.append(Outcome("active", "unmet", machine.health_status or "unknown"))
        for tag in expectations.tags:
            check = f"tag {tag}"
            if defender_error:
                outcomes.append(Outcome(check, "error", defender_error))
            elif machine is None:
                outcomes.append(Outcome(check, "unmet", "no Defender record"))
            elif tag.casefold() in {item.casefold() for item in machine.machine_tags}:
                outcomes.append(Outcome(check, "met", "tagged"))
            else:
                outcomes.append(Outcome(check, "unmet", "tag missing"))
        for device_group in expectations.device_groups:
            check = f"device group {device_group}"
            if defender_error:
                outcomes.append(Outcome(check, "error", defender_error))
            elif machine is None:
                outcomes.append(Outcome(check, "unmet", "no Defender record"))
            elif machine.device_group.casefold() == device_group.casefold():
                outcomes.append(Outcome(check, "met", "in the device group"))
            else:
                outcomes.append(Outcome(check, "unmet", f"in {machine.device_group or 'none'}"))
        for group in expectations.groups:
            check = f"group {group}"
            if errors.get("entra"):
                outcomes.append(Outcome(check, "error", errors["entra"]))
            elif not entra_devices:
                outcomes.append(Outcome(check, "unmet", "not in Entra"))
            elif any(device.id in members.get(group, frozenset()) for device in entra_devices):
                outcomes.append(Outcome(check, "met", "member"))
            else:
                outcomes.append(Outcome(check, "unmet", "not a member"))
        newest = managed[0] if managed else None
        if expectations.in_intune:
            if errors.get("intune"):
                outcomes.append(Outcome("intune", "error", errors["intune"]))
            elif newest is None:
                outcomes.append(Outcome("intune", "unmet", "not enrolled in Intune"))
            else:
                outcomes.append(Outcome("intune", "met", newest.management_agent or "enrolled"))
        if expectations.compliant:
            if errors.get("intune"):
                outcomes.append(Outcome("compliant", "error", errors["intune"]))
            elif newest is None:
                outcomes.append(Outcome("compliant", "unmet", "not enrolled in Intune"))
            elif newest.compliant:
                outcomes.append(Outcome("compliant", "met", "compliant"))
            else:
                outcomes.append(Outcome("compliant", "unmet", newest.compliance_state or "unknown"))
        return DeviceReport(name, tuple(outcomes), entra_devices, lookup, managed)


def watch(
    checker: DeviceChecker,
    names: Sequence[str],
    expectations: Expectations,
    limits: PollLimits,
    *,
    recheck: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_pass: Callable[[int, CheckRun], None] | None = None,
    on_wait: Callable[[float], None] | None = None,
) -> PollOutcome[CheckRun]:
    """Check ``names`` every ``limits.interval`` until all are complete or a limit hits.

    A device that met everything is not checked again unless ``recheck`` is set, so
    later passes only cost calls for the devices still outstanding. A pass that fails
    outright (other than on a rejected token) is reported and the next pass tries again.
    """
    latest: dict[str, DeviceReport] = {}
    order = list(names)

    def current(error: str | None = None) -> CheckRun:
        reports = tuple(latest[name] for name in order if name in latest)
        return CheckRun(reports, utc_now(), len(order), error)

    def run_pass(_number: int) -> CheckRun:
        pending = (
            order
            if recheck
            else [name for name in order if name not in latest or not latest[name].complete]
        )
        try:
            run = checker.check(pending, expectations)
        except ApiError as exc:
            if exc.status in _FATAL:
                raise
            return current(str(exc))
        for report in run.reports:
            latest[report.name] = report
        return current()

    return poll(
        run_pass,
        lambda run: run.complete,
        limits,
        clock=clock,
        sleep=sleep,
        on_pass=on_pass,
        on_wait=on_wait,
    )


def _guarded(errors: dict[str, str], key: str, call: Callable[[], T], default: T) -> T:
    try:
        return call()
    except ApiError as exc:
        if exc.status in _FATAL:
            raise
        errors[key] = str(exc)
        return default


def _entra_outcome(devices: tuple[EntraDevice, ...], error: str | None) -> Outcome:
    if error:
        return Outcome("entra", "error", error)
    if not devices:
        return Outcome("entra", "unmet", "not in Entra")
    if all(device.enabled is False for device in devices):
        return Outcome("entra", "unmet", "disabled in Entra")
    detail = "present" if len(devices) == 1 else f"{len(devices)} objects share the name"
    return Outcome("entra", "met", detail)
