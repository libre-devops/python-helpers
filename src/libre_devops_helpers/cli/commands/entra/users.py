"""Entra users: their groups, their directory roles, and sign-ins."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands.entra.groups import group_rows
from libre_devops_helpers.cli.options import (
    DirectOption,
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.util import format_span
from libre_devops_helpers.microsoft.entra import RoleAssignment


def register(app: typer.Typer) -> None:
    """Add ``user-groups``, ``user-roles`` and ``sign-ins`` to ``app``."""
    app.command("user-groups")(user_groups)
    app.command("user-roles")(user_roles)
    app.command("sign-ins")(sign_ins)


def user_groups(
    ctx: typer.Context,
    user: Annotated[str, typer.Argument(help="User principal name, object id or display name.")],
    profile: ProfileOption = None,
    direct: DirectOption = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the Entra groups a user belongs to."""
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    found = entra.get_user(user)
    groups = entra.user_groups(found, transitive=not direct)
    if output is Output.TABLE:
        render.echo(
            render.title(f"{found.user_principal_name}  object {found.id}  {len(groups)} group(s)")
        )
    render.emit(
        output,
        ["GROUP", "OBJECT ID", "MEMBERSHIP", "SECURITY"],
        group_rows(groups),
        {"user": dict(found.raw), "groups": [dict(group.raw) for group in groups]},
    )


def user_roles(
    ctx: typer.Context,
    user: Annotated[str, typer.Argument(help="User principal name, object id or display name.")],
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the directory roles a user holds now, and those PIM makes them eligible for."""
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    found = entra.get_user(user)
    report = entra.user_roles(found)
    roles: list[RoleAssignment] = [*report.active, *(report.eligible or ())]
    if output is Output.TABLE:
        render.echo(render.title(f"{found.user_principal_name}  object {found.id}"))
    render.emit(
        output,
        ["ROLE", "STATE", "SCOPE", "ENDS"],
        [
            [
                role.role_name,
                ("active", "green") if role.state == "active" else ("eligible", "yellow"),
                role.scope,
                render.when(role.ends) if role.ends else "permanent",
            ]
            for role in roles
        ],
        {
            "user": dict(found.raw),
            "active": [dict(role.raw) for role in report.active],
            "eligible": None
            if report.eligible is None
            else [dict(role.raw) for role in report.eligible],
            "eligible_error": report.eligible_error,
        },
    )
    if report.eligible is None:
        render.warn(f"PIM eligibility could not be read: {report.eligible_error}")


def sign_ins(
    ctx: typer.Context,
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Only this user (UPN or object id).")
    ] = None,
    since: Annotated[
        str, typer.Option("--since", help="How far back to look, e.g. 1h, 24h, 7d.")
    ] = "24h",
    failures: Annotated[bool, typer.Option("--failures", help="Only failed sign-ins.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most sign-ins to show.")] = 50,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List recent sign-ins, newest first. Needs Entra ID P1."""
    window = duration(since) or timedelta(hours=24)
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    events = entra.sign_ins(
        user=user, since=datetime.now(UTC) - window, failures_only=failures, limit=limit
    )
    render.emit(
        output,
        ["WHEN", "USER", "APP", "RESULT", "IP", "LOCATION", "DEVICE", "CA"],
        [
            [
                render.when(event.created),
                event.user,
                event.app,
                ("success", "green")
                if event.succeeded
                else (f"{event.error_code} {event.failure_reason}", "red"),
                event.ip_address,
                event.location,
                event.device_name,
                event.conditional_access,
            ]
            for event in events
        ],
        [dict(event.raw) for event in events],
    )
    if output is Output.TABLE:
        render.note(f"{len(events)} sign-in(s) in the last {format_span(window)}")
