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
from libre_devops_helpers.core.errors import ApiError, ReauthRequired
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
from libre_devops_helpers.microsoft.xdr.models import Machine, MachineLookup

_FATAL = frozenset({401, 403})

T = TypeVar("T")
R = TypeVar("R")
# A judge looks at the record a lookup found and says whether a check is met, and why.
Judge = Callable[[R], tuple[bool, str]]


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
            raise ValueError("workers must be at least 1")
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
            raise ValueError(f"these checks need a client for {', '.join(missing)}")

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
        """Look ``name`` up in each service the checks need, then judge every check."""
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

        machine = lookup.machine if lookup is not None else None
        newest = managed[0] if managed else None
        outcomes: list[Outcome] = []
        if expectations.in_entra:
            outcomes.append(_entra_outcome(entra_devices, errors.get("entra")))
        outcomes += _defender_outcomes(expectations, machine, errors.get("defender"))
        outcomes += _group_outcomes(
            expectations.groups, entra_devices, members, errors.get("entra")
        )
        outcomes += _intune_outcomes(expectations, newest, errors.get("intune"))
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


# Judging the checks ----------------------------------------------------------------------
#
# Every check has the same shape: the lookup failed (error), it found nothing (unmet, and
# why), or it found a record, which a judge meets or not with a detail. ``_judge`` holds
# that shape once; each service lists its checks as (name, judge) pairs.


def _judge(
    check: str, error: str | None, found: R | None, missing: str, judge: Judge[R]
) -> Outcome:
    if error:
        return Outcome(check, "error", error)
    if found is None:
        return Outcome(check, "unmet", missing)
    met, detail = judge(found)
    return Outcome(check, "met" if met else "unmet", detail)


def _defender_outcomes(
    expectations: Expectations, machine: Machine | None, error: str | None
) -> list[Outcome]:
    """Onboarded, active, each tag and each device group, from the Defender record."""
    checks: list[tuple[str, Judge[Machine]]] = []
    if expectations.onboarded:
        checks.append(("defender", _onboarded))
    if expectations.active:
        checks.append(("active", _active))
    checks += [(f"tag {tag}", _has_tag(tag)) for tag in expectations.tags]
    checks += [
        (f"device group {group}", _in_device_group(group)) for group in expectations.device_groups
    ]
    return [_judge(check, error, machine, "no Defender record", judge) for check, judge in checks]


def _onboarded(machine: Machine) -> tuple[bool, str]:
    if machine.onboarding_status == "Onboarded":
        return True, f"onboarded, {machine.health_status}"
    return False, machine.onboarding_status or "not onboarded"


def _active(machine: Machine) -> tuple[bool, str]:
    if machine.health_status == "Active":
        return True, "Active"
    return False, machine.health_status or "unknown"


def _has_tag(tag: str) -> Judge[Machine]:
    def judge(machine: Machine) -> tuple[bool, str]:
        tagged = tag.casefold() in {item.casefold() for item in machine.machine_tags}
        return tagged, "tagged" if tagged else "tag missing"

    return judge


def _in_device_group(group: str) -> Judge[Machine]:
    def judge(machine: Machine) -> tuple[bool, str]:
        if machine.device_group.casefold() == group.casefold():
            return True, "in the device group"
        return False, f"in {machine.device_group or 'none'}"

    return judge


def _group_outcomes(
    groups: Sequence[str],
    devices: tuple[EntraDevice, ...],
    members: Mapping[str, frozenset[str]],
    error: str | None,
) -> list[Outcome]:
    """Membership of each Entra group, by any of the Entra objects that share the name."""

    def member_of(group: str) -> Judge[tuple[EntraDevice, ...]]:
        def judge(found: tuple[EntraDevice, ...]) -> tuple[bool, str]:
            ids = members.get(group, frozenset())
            joined = any(device.id in ids for device in found)
            return joined, "member" if joined else "not a member"

        return judge

    return [
        _judge(f"group {group}", error, devices or None, "not in Entra", member_of(group))
        for group in groups
    ]


def _intune_outcomes(
    expectations: Expectations, newest: ManagedDevice | None, error: str | None
) -> list[Outcome]:
    """Enrolled and compliant, from the newest Intune record."""
    checks: list[tuple[str, Judge[ManagedDevice]]] = []
    if expectations.in_intune:
        checks.append(("intune", _enrolled))
    if expectations.compliant:
        checks.append(("compliant", _compliant))
    return [
        _judge(check, error, newest, "not enrolled in Intune", judge) for check, judge in checks
    ]


def _enrolled(device: ManagedDevice) -> tuple[bool, str]:
    return True, device.management_agent or "enrolled"


def _compliant(device: ManagedDevice) -> tuple[bool, str]:
    if device.compliant:
        return True, "compliant"
    return False, device.compliance_state or "unknown"
