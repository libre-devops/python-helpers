"""Defender for Endpoint commands: machines, stale machines, alerts, vulnerabilities, hunting."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    ColumnOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    QueryFileOption,
    duration,
    get_runtime,
    names,
    read_query,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import LdoError, NotFoundError
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.xdr import Machine, MachineLookup, parse_severity

xdr_app = typer.Typer(
    help="Defender for Endpoint: machines, alerts, vulnerabilities and hunting.",
    no_args_is_help=True,
)

_SEVERITY_COLOURS = {"critical": "red", "high": "red", "medium": "yellow"}


def register(app: typer.Typer) -> None:
    app.add_typer(xdr_app, name="xdr")


@xdr_app.command("machines")
def machines(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    profile: ProfileOption = None,
    all_records: Annotated[
        bool, typer.Option("--all-records", help="Also list older duplicate Defender records.")
    ] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Look devices up in Defender: onboarding, health, last seen and tags.

    Each device is looked up by FQDN, then by short hostname. Exits 3 when any device
    has no Defender record.
    """
    wanted = names(devices, from_file, column)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    lookups = runtime.xdr(selected).find_machines(wanted)
    render.emit(
        output,
        [
            "DEVICE",
            "MATCHED",
            "ONBOARDING",
            "HEALTH",
            "LAST SEEN",
            "OS",
            "TAGS",
            "RECORDS",
            "MACHINE ID",
        ],
        _machine_rows(lookups, all_records=all_records),
        [
            {
                "query": lookup.query,
                "matched_name": lookup.matched_name,
                "found": lookup.found,
                "records": [dict(record.raw) for record in lookup.records],
            }
            for lookup in lookups
        ],
    )
    missing = [lookup.query for lookup in lookups if not lookup.found]
    render.note(
        f"{len(lookups) - len(missing)} of {len(lookups)} found in Defender "
        f"(profile {selected.name})"
    )
    if missing:
        raise typer.Exit(ATTENTION)


def _machine_rows(lookups: list[MachineLookup], *, all_records: bool) -> list[list[render.Cell]]:
    rows: list[list[render.Cell]] = []
    for lookup in lookups:
        if lookup.machine is None:
            rows.append([lookup.query, ("not found", "red"), "", "", "", "", "", "0", ""])
            continue
        matched = "fqdn" if lookup.matched_name == lookup.query.strip().rstrip(".") else "short"
        rows.append(
            [
                lookup.query,
                matched,
                *_machine_cells(lookup.machine),
                str(len(lookup.records)),
                lookup.machine.id,
            ]
        )
        if all_records:
            for older in lookup.records[1:]:
                rows.append(
                    [("  older record", "bright_black"), "", *_machine_cells(older), "", older.id]
                )
    return rows


def _machine_cells(machine: Machine) -> list[render.Cell]:
    onboarded = machine.onboarding_status == "Onboarded"
    health_colour = {"Active": "green", "Inactive": "yellow"}.get(machine.health_status, "red")
    return [
        (machine.onboarding_status, "green" if onboarded else "yellow"),
        (machine.health_status, health_colour),
        render.when(machine.last_seen),
        f"{machine.os_platform} {machine.os_version}".strip(),
        ",".join(machine.machine_tags),
    ]


@xdr_app.command("stale")
def stale(
    ctx: typer.Context,
    older_than: Annotated[
        str, typer.Option("--older-than", help="Not seen for at least this long, e.g. 30d.")
    ] = "30d",
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List machines Defender has not seen recently, longest silent first.

    Exits 3 when any are found.
    """
    window = duration(older_than) or timedelta(days=30)
    runtime = get_runtime(ctx).microsoft
    found = runtime.xdr(runtime.profile(profile)).stale_machines(window)
    render.emit(
        output,
        ["DEVICE", "LAST SEEN", "HEALTH", "ONBOARDING", "OS", "TAGS", "MACHINE ID"],
        [
            [
                machine.computer_dns_name,
                render.when(machine.last_seen),
                machine.health_status,
                machine.onboarding_status,
                f"{machine.os_platform} {machine.os_version}".strip(),
                ",".join(machine.machine_tags),
                machine.id,
            ]
            for machine in found
        ],
        [dict(machine.raw) for machine in found],
    )
    render.note(f"{len(found)} machine(s) not seen for {format_duration(window)}")
    if found:
        raise typer.Exit(ATTENTION)


@xdr_app.command("alerts")
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


@xdr_app.command("vulns")
def vulns(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name: FQDN or short hostname.")],
    severity: Annotated[
        str | None,
        typer.Option("--severity", help="At least this severity: low, medium, high, critical."),
    ] = None,
    profile: ProfileOption = None,
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


@xdr_app.command("indicators")
def indicators(
    ctx: typer.Context,
    profile: ProfileOption = None,
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


@xdr_app.command("hunt")
def hunt(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(
            help="KQL query. Omit, or pass -, to read it from stdin.", show_default=False
        ),
    ] = None,
    file: QueryFileOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run an Advanced Hunting (KQL) query against Defender."""
    text = read_query(query, file)
    runtime = get_runtime(ctx).microsoft
    result = runtime.xdr(runtime.profile(profile)).hunt(text)
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")
