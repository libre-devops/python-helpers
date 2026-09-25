"""Entra devices: looking names up (and checking group membership), and a device's groups."""

from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands.entra.groups import group_rows
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    ColumnOption,
    DirectOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    SheetOption,
    SortOption,
    UniqueOption,
    WhereOption,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import NotFoundError
from libre_devops_helpers.core.util import candidate_names
from libre_devops_helpers.microsoft.entra import DeviceLookup


def register(app: typer.Typer) -> None:
    """Add ``devices`` and ``device-groups`` to ``app``."""
    app.command("devices")(devices)
    app.command("device-groups")(device_groups)


def devices(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    where: WhereOption = None,
    group: Annotated[
        list[str] | None,
        typer.Option(
            "--group",
            help="Also check each device is in this Entra group: its object id or display "
            "name. Repeatable.",
        ),
    ] = None,
    direct: DirectOption = False,
    workers: Annotated[
        int, typer.Option("--workers", min=1, max=32, help="Devices looked up at once.")
    ] = 8,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Look devices up in Entra ID, and check they are in the groups you name.

    Each device is looked up by FQDN, then by short hostname, and every registration with
    the name is shown. --group takes a group's object id or its display name (a name two
    groups share is refused), and counts nested membership unless --direct. Exits 3 when
    a device is not in Entra, or not in every group.
    """
    wanted = names(devices, from_file, column, sheet, where)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    entra = runtime.entra(selected)
    groups = [entra.get_group(ref) for ref in group or []]
    lookups = entra.look_up_devices(wanted, groups, transitive=not direct, workers=workers)
    headers = ["DEVICE", "NAME", "OS", "ENABLED", "TRUST", "LAST SIGN-IN", "DEVICE ID"]
    render.emit(
        output,
        [*headers, *[f"IN {found.display_name}" for found in groups]],
        [row for lookup in lookups for row in _lookup_rows(lookup)],
        [_lookup_record(lookup) for lookup in lookups],
    )
    found = [lookup for lookup in lookups if lookup.found]
    note = f"{len(found)} of {len(lookups)} in Entra"
    if groups:
        note += f", {sum(1 for lookup in found if lookup.in_every_group)} in every group"
    render.note(note + f" (profile {selected.name})")
    if len(found) < len(lookups) or not all(lookup.in_every_group for lookup in found):
        raise typer.Exit(ATTENTION)


def _lookup_rows(lookup: DeviceLookup) -> list[list[render.Cell]]:
    """A row for each device with the name, the most recently signed in first (the rest
    are marked as older records), or one row saying there is none."""
    if not lookup.found:
        return [[lookup.query, ("not in Entra", "red"), *[""] * (5 + len(lookup.groups))]]
    return [
        [
            lookup.query if index == 0 else ("  older record", "bright_black"),
            device.display_name,
            f"{device.operating_system} {device.os_version}".strip(),
            render.yes_no(device.enabled),
            device.trust_type,
            render.when(device.last_sign_in),
            device.device_id,
            *[
                ("yes", "green") if lookup.in_group(group, device) else ("no", "yellow")
                for group in lookup.groups
            ],
        ]
        for index, device in enumerate(lookup.devices)
    ]


def _lookup_record(lookup: DeviceLookup) -> dict[str, Any]:
    return {
        "query": lookup.query,
        "found": lookup.found,
        "groups": [
            {"id": group.id, "name": group.display_name, "member": lookup.in_group(group)}
            for group in lookup.groups
        ],
        "devices": [dict(device.raw) for device in lookup.devices],
    }


def device_groups(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name: FQDN or short hostname.")],
    profile: ProfileOption = None,
    direct: DirectOption = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the Entra groups a device belongs to."""
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    devices = entra.find_devices(device)
    if not devices:
        tried = " or ".join(repr(name) for name in candidate_names(device))
        raise NotFoundError(f"no Entra device is named {tried}")
    results = [(found, entra.device_groups(found, transitive=not direct)) for found in devices]

    if output is not Output.TABLE:
        render.emit(
            output,
            ["DEVICE", "DEVICE OBJECT ID", "GROUP", "GROUP OBJECT ID", "MEMBERSHIP", "SECURITY"],
            [
                [found.display_name, found.id, *row]
                for found, groups in results
                for row in group_rows(groups)
            ],
            [
                {"device": dict(found.raw), "groups": [dict(group.raw) for group in groups]}
                for found, groups in results
            ],
        )
        return
    if len(devices) > 1:
        render.warn(
            f"{len(devices)} Entra devices are named {devices[0].display_name!r} "
            "(stale registrations keep the name)"
        )
    for found, groups in results:
        render.echo(
            render.title(
                f"{found.display_name}  object {found.id}  {found.operating_system} "
                f"{found.os_version}  last sign-in {render.when(found.last_sign_in)}"
            )
        )
        if groups:
            render.echo(
                render.table(["GROUP", "OBJECT ID", "MEMBERSHIP", "SECURITY"], group_rows(groups))
            )
        else:
            render.echo("(no group memberships)")
        render.echo()
