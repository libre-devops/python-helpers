"""One device across Entra, Defender and Intune, and what looks wrong about it.

Entra is required: it is where a device's identity lives. Defender and Intune are
optional, and a failure reading either one (a suspended service, a token without the
scope) becomes a finding rather than an error, so the rest of the picture still shows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from libre_devops_helpers.core.auth import utc_now
from libre_devops_helpers.core.errors import ApiError
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.devices.models import DeviceView, Finding
from libre_devops_helpers.microsoft.entra.client import EntraClient
from libre_devops_helpers.microsoft.entra.models import EntraDevice, EntraGroup
from libre_devops_helpers.microsoft.intune.client import IntuneClient
from libre_devops_helpers.microsoft.intune.models import ManagedDevice
from libre_devops_helpers.microsoft.xdr.client import XdrClient
from libre_devops_helpers.microsoft.xdr.models import MachineLookup


def inspect_device(
    name: str,
    *,
    entra: EntraClient,
    xdr: XdrClient | None = None,
    intune: IntuneClient | None = None,
    stale_after: timedelta = timedelta(days=7),
    now: datetime | None = None,
) -> DeviceView:
    """Everything the services know about ``name``, with findings worth acting on."""
    now = now or utc_now()
    findings: list[Finding] = []

    devices = tuple(entra.find_devices(name))
    groups: dict[str, tuple[EntraGroup, ...]] = {
        device.id: tuple(entra.device_groups(device)) for device in devices
    }
    findings.extend(_entra_findings(devices))

    lookup: MachineLookup | None = None
    if xdr is not None:
        try:
            lookup = xdr.find_machine(name)
        except ApiError as exc:
            findings.append(Finding("warn", f"Defender could not be read: {exc}"))
        else:
            findings.extend(_defender_findings(lookup, devices, stale_after, now))

    managed: tuple[ManagedDevice, ...] | None = None
    if intune is not None:
        try:
            managed = tuple(intune.find_devices(name))
        except ApiError as exc:
            findings.append(Finding("warn", f"Intune could not be read: {exc}"))
        else:
            findings.extend(_intune_findings(managed, devices))

    if not any(finding.level == "warn" for finding in findings):
        findings.append(Finding("ok", "nothing looks wrong"))
    return DeviceView(name, devices, groups, lookup, managed, tuple(findings))


def _entra_findings(devices: tuple[EntraDevice, ...]) -> list[Finding]:
    if not devices:
        return [Finding("warn", "not in Entra")]
    found: list[Finding] = []
    if len(devices) > 1:
        found.append(
            Finding("warn", f"{len(devices)} Entra objects share this name (stale registrations)")
        )
    found.extend(
        Finding("warn", f"Entra object {device.id} is disabled")
        for device in devices
        if device.enabled is False
    )
    return found


def _defender_findings(
    lookup: MachineLookup,
    devices: tuple[EntraDevice, ...],
    stale_after: timedelta,
    now: datetime,
) -> list[Finding]:
    machine = lookup.machine
    if machine is None:
        return [Finding("warn", "no Defender record")]
    found: list[Finding] = []
    if len(lookup.records) > 1:
        found.append(Finding("warn", f"{len(lookup.records)} Defender records; the newest is used"))
    if lookup.matched_name != lookup.query.strip().rstrip("."):
        found.append(Finding("info", f"Defender knows it by its short name {lookup.matched_name}"))
    if machine.onboarding_status != "Onboarded":
        found.append(
            Finding("warn", f"Defender onboarding status is {machine.onboarding_status or '-'}")
        )
    if machine.health_status != "Active":
        found.append(Finding("warn", f"Defender health is {machine.health_status or '-'}"))
    if machine.last_seen is not None and now - machine.last_seen > stale_after:
        found.append(
            Finding("warn", f"Defender last saw it {format_duration(now - machine.last_seen)} ago")
        )
    if not machine.aad_device_id:
        found.append(
            Finding(
                "info", "Defender has no Entra device id for it (not Entra joined or registered)"
            )
        )
    elif devices and machine.aad_device_id.lower() not in {d.device_id.lower() for d in devices}:
        found.append(
            Finding(
                "warn",
                f"Defender links it to Entra device {machine.aad_device_id}, "
                "which is not one of the Entra objects with this name",
            )
        )
    return found


def _intune_findings(
    managed: tuple[ManagedDevice, ...], devices: tuple[EntraDevice, ...]
) -> list[Finding]:
    if not managed:
        return [Finding("info", "not enrolled in Intune")]
    newest = managed[0]
    found: list[Finding] = []
    if len(managed) > 1:
        found.append(Finding("warn", f"{len(managed)} Intune records; the newest sync is used"))
    if not newest.compliant:
        found.append(Finding("warn", f"Intune compliance is {newest.compliance_state or '-'}"))
    if (
        newest.azure_ad_device_id
        and devices
        and newest.azure_ad_device_id.lower() not in {d.device_id.lower() for d in devices}
    ):
        found.append(
            Finding(
                "warn",
                f"Intune links it to Entra device {newest.azure_ad_device_id}, "
                "which is not one of the Entra objects with this name",
            )
        )
    return found
