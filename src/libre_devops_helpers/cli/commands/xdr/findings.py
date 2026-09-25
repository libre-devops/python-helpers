"""What Defender has found or holds: alerts, a device's vulnerabilities, and custom indicators."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import LdoError, NotFoundError
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.xdr import parse_severity


def register(app: typer.Typer) -> None:
    """Add ``alerts``, ``vulns`` and ``indicators`` to ``app``."""
    app.command("alerts")(alerts)
    app.command("vulns")(vulns)
    app.command("indicators")(indicators)


_SEVERITY_COLOURS = {"critical": "red", "high": "red", "medium": "yellow"}


def alerts(
    ctx: typer.Context,
    device: Annotated[
        str | None, typer.Option("--device", "-d", help="Only alerts for this device name.")
    ] = None,
    since: Annotated[str, typer.Option("--since", help="How far back, e.g. 24h, 7d.")] = "7d",
    severity: Annotated[
        str | None,
        typer.Option("--severity", help="At least this severity: low, medium or high."),
    ] = None,
    include_resolved: Annotated[
        bool, typer.Option("--include-resolved", help="Include resolved alerts.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most alerts to show.")] = 200,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List Defender alerts, newest first: open ones unless --include-resolved."""
    if severity is not None:
        parse_severity(severity)
    window = duration(since) or timedelta(days=7)
    runtime = get_runtime(ctx).microsoft
    xdr = runtime.xdr(runtime.profile(profile))
    machine_id = None
    if device is not None:
        lookup = xdr.find_machine(device)
        if lookup.machine is None:
            raise NotFoundError(f"no Defender record for {device!r}")
        machine_id = lookup.machine.id
    found = xdr.alerts(
        machine_id=machine_id,
        since=datetime.now(UTC) - window,
        min_severity=severity,
        include_resolved=include_resolved,
        limit=limit,
    )
    render.emit(
        output,
        ["CREATED", "SEVERITY", "STATUS", "TITLE", "DEVICE", "CATEGORY", "SOURCE", "ALERT ID"],
        [
            [
                render.when(alert.created),
                (alert.severity, _SEVERITY_COLOURS.get(alert.severity.casefold())),
                alert.status,
                alert.title,
                alert.computer_dns_name,
                alert.category,
                alert.detection_source,
                alert.id,
            ]
            for alert in found
        ],
        [dict(alert.raw) for alert in found],
    )
    render.note(f"{len(found)} alert(s) in the last {format_duration(window)}")


def vulns(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name: FQDN or short hostname.")],
    severity: Annotated[
        str | None,
        typer.Option("--severity", help="At least this severity: low, medium, high, critical."),
    ] = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the vulnerabilities Defender reports on a device, most severe first."""
    floor = parse_severity(severity) if severity else None
    runtime = get_runtime(ctx).microsoft
    xdr = runtime.xdr(runtime.profile(profile))
    lookup = xdr.find_machine(device)
    if lookup.machine is None:
        raise NotFoundError(f"no Defender record for {device!r}")
    found = xdr.vulnerabilities(lookup.machine.id)
    if floor is not None:
        found = [item for item in found if _rank(item.severity) >= floor]
    render.emit(
        output,
        ["CVE", "SEVERITY", "CVSS", "EXPLOIT", "PUBLISHED", "NAME"],
        [
            [
                item.id,
                (item.severity, _SEVERITY_COLOURS.get(item.severity.casefold())),
                "" if item.cvss is None else f"{item.cvss:.1f}",
                "verified" if item.exploit_verified else "public" if item.public_exploit else "",
                render.when(item.published),
                item.name,
            ]
            for item in found
        ],
        [dict(item.raw) for item in found],
    )
    render.note(f"{len(found)} vulnerabilit{'y' if len(found) == 1 else 'ies'} on {device}")


def _rank(severity: str) -> int:
    try:
        return parse_severity(severity)
    except LdoError:
        return -1


def indicators(
    ctx: typer.Context,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List custom indicators of compromise (hashes, IPs, URLs, domains, certificates)."""
    runtime = get_runtime(ctx).microsoft
    found = runtime.xdr(runtime.profile(profile)).indicators()
    render.emit(
        output,
        ["TYPE", "VALUE", "ACTION", "SEVERITY", "TITLE", "EXPIRES", "CREATED BY"],
        [
            [
                item.indicator_type,
                item.value,
                item.action,
                item.severity,
                item.title,
                render.when(item.expires),
                item.created_by,
            ]
            for item in found
        ],
        [dict(item.raw) for item in found],
    )
