"""Defender machines: looking devices up, and those that have gone quiet."""

from datetime import timedelta
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
    SheetOption,
    SortOption,
    UniqueOption,
    WhereOption,
    duration,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.util import format_span, short_name
from libre_devops_helpers.microsoft.xdr import Machine, MachineLookup


def register(app: typer.Typer) -> None:
    """Add ``machines`` and ``stale`` to ``app``."""
    app.command("machines")(machines)
    app.command("stale")(stale)


def machines(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    where: WhereOption = None,
    profile: ProfileOption = None,
    all_records: Annotated[
        bool, typer.Option("--all-records", help="Also list older duplicate Defender records.")
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Look devices up in Defender: onboarding, health, last seen, tags and device group.

    Each device is looked up by FQDN, then by short hostname. Exits 3 when any device
    has no Defender record.
    """
    wanted = names(devices, from_file, column, sheet, where)
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
            "DEVICE GROUP",
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
            rows.append([lookup.query, ("not found", "red"), "", "", "", "", "", "", "0", ""])
            continue
        query = lookup.query.strip().rstrip(".")
        if lookup.matched_name == query:
            matched = "fqdn"
        elif lookup.matched_name == short_name(query):
            matched = "short"
        else:
            matched = "prefix"  # a short name, found as the first label of Defender's FQDN
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
        machine.device_group,
    ]


def stale(
    ctx: typer.Context,
    older_than: Annotated[
        str, typer.Option("--older-than", help="Not seen for at least this long, e.g. 30d.")
    ] = "30d",
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
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
    render.note(f"{len(found)} machine(s) not seen for {format_span(window)}")
    if found:
        raise typer.Exit(ATTENTION)
