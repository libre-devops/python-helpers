"""Entra groups: the devices in one, and its members of every kind."""

from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    DirectOption,
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.microsoft.entra import (
    EntraGroup,
    MemberKind,
)


def register(app: typer.Typer) -> None:
    """Add ``group-devices`` and ``group-members`` to ``app``."""
    app.command("group-devices")(group_devices)
    app.command("group-members")(group_members)


def group_devices(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group display name or object id.")],
    profile: ProfileOption = None,
    direct: DirectOption = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the devices in an Entra group."""
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    found = entra.get_group(group)
    devices = entra.group_devices(found, transitive=not direct)
    if output is Output.TABLE:
        membership = "dynamic" if found.dynamic else "assigned"
        render.echo(
            render.title(
                f"{found.display_name}  object {found.id}  {membership}  {len(devices)} device(s)"
            )
        )
    render.emit(
        output,
        ["DEVICE", "OS", "VERSION", "ENABLED", "TRUST", "LAST SIGN-IN", "DEVICE ID"],
        [
            [
                device.display_name,
                device.operating_system,
                device.os_version,
                render.yes_no(device.enabled),
                device.trust_type,
                render.when(device.last_sign_in),
                device.device_id,
            ]
            for device in devices
        ],
        {"group": dict(found.raw), "devices": [dict(device.raw) for device in devices]},
    )


def group_members(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group display name or object id.")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Only this kind: user, device, group or servicePrincipal."),
    ] = None,
    profile: ProfileOption = None,
    direct: DirectOption = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the members of an Entra group, of every kind or of one."""
    kinds: dict[str, MemberKind] = {
        "user": "user",
        "device": "device",
        "group": "group",
        "serviceprincipal": "servicePrincipal",
    }
    if kind is not None and kind.casefold() not in kinds:
        raise typer.BadParameter(f"--kind must be one of {', '.join(kinds.values())}")
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    found = entra.get_group(group)
    members = entra.group_members(
        found, transitive=not direct, kind=kinds[kind.casefold()] if kind else None
    )
    if output is Output.TABLE:
        render.echo(render.title(f"{found.display_name}  {len(members)} member(s)"))
    render.emit(
        output,
        ["KIND", "NAME", "DETAIL", "OBJECT ID"],
        [[member.kind, member.display_name, member.detail, member.id] for member in members],
        {"group": dict(found.raw), "members": [dict(member.raw) for member in members]},
    )


def group_rows(groups: list[EntraGroup]) -> list[list[render.Cell]]:
    """Table rows for ``groups`` (GROUP, OBJECT ID, MEMBERSHIP, SECURITY), shared by the
    commands that list a device's or a user's groups."""
    return [
        [
            group.display_name,
            group.id,
            "dynamic" if group.dynamic else "assigned",
            render.yes_no(group.security_enabled),
        ]
        for group in groups
    ]
