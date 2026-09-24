"""Entra commands: devices, users, groups, roles, sign-ins, app credentials, CA policies."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    ColumnOption,
    DirectOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    SheetOption,
    duration,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import NotFoundError
from libre_devops_helpers.core.util import candidate_names, format_duration, is_guid
from libre_devops_helpers.microsoft.entra import (
    AppCredential,
    EntraDevice,
    EntraGroup,
    MemberKind,
    RoleAssignment,
    expiring,
)

entra_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Entra ID: devices, users, groups, roles and apps.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    app.add_typer(entra_app, name="entra")


def _group_rows(groups: list[EntraGroup]) -> list[list[render.Cell]]:
    return [
        [
            group.display_name,
            group.id,
            "dynamic" if group.dynamic else "assigned",
            render.yes_no(group.security_enabled),
        ]
        for group in groups
    ]


@entra_app.command("devices")
def devices(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
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
    output: OutputOption = Output.TABLE,
) -> None:
    """Look devices up in Entra ID, and check they are in the groups you name.

    Each device is looked up by FQDN, then by short hostname, and every registration with
    the name is shown. --group takes a group's object id or its display name (a name two
    groups share is refused), and counts nested membership unless --direct. Exits 3 when
    a device is not in Entra, or not in every group.
    """
    wanted = names(devices, from_file, column, sheet)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    entra = runtime.entra(selected)
    # Groups first, on this thread: each is resolved and its members fetched once, and a
    # lapsed sign-in is met here, where it can be renewed, rather than in a worker.
    groups = [entra.get_group(ref) for ref in group or []]
    members = {
        found.id: frozenset(item.id for item in entra.group_devices(found, transitive=not direct))
        for found in groups
    }
    first = [entra.find_devices(wanted[0])]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            zip(wanted, first + list(pool.map(entra.find_devices, wanted[1:])), strict=True)
        )

    def member(found: EntraGroup, records: list[EntraDevice]) -> bool:
        return any(record.id in members[found.id] for record in records)

    rows: list[list[render.Cell]] = []
    for name, records in results:
        if not records:
            rows.append([name, ("not in Entra", "red"), "", "", "", "", "", *["" for _ in groups]])
            continue
        for index, record in enumerate(records):
            rows.append(
                [
                    name if index == 0 else ("  older record", "bright_black"),
                    record.display_name,
                    f"{record.operating_system} {record.os_version}".strip(),
                    render.yes_no(record.enabled),
                    record.trust_type,
                    render.when(record.last_sign_in),
                    record.device_id,
                    *[
                        ("yes", "green") if member(found, [record]) else ("no", "yellow")
                        for found in groups
                    ],
                ]
            )
    records_out: list[dict[str, Any]] = [
        {
            "query": name,
            "found": bool(records),
            "groups": [
                {"id": found.id, "name": found.display_name, "member": member(found, records)}
                for found in groups
            ],
            "devices": [dict(record.raw) for record in records],
        }
        for name, records in results
    ]
    render.emit(
        output,
        [
            "DEVICE",
            "NAME",
            "OS",
            "ENABLED",
            "TRUST",
            "LAST SIGN-IN",
            "DEVICE ID",
            *[f"IN {found.display_name}" for found in groups],
        ],
        rows,
        records_out,
    )
    missing = sum(1 for _, records in results if not records)
    outside = sum(
        1 for _, records in results if records and not all(member(g, records) for g in groups)
    )
    note = f"{len(results) - missing} of {len(results)} in Entra"
    if groups:
        note += f", {len(results) - missing - outside} in every group"
    render.note(note + f" (profile {selected.name})")
    if missing or outside:
        raise typer.Exit(ATTENTION)


@entra_app.command("device-groups")
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
                for row in _group_rows(groups)
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
                render.table(["GROUP", "OBJECT ID", "MEMBERSHIP", "SECURITY"], _group_rows(groups))
            )
        else:
            render.echo("(no group memberships)")
        render.echo()


@entra_app.command("group-devices")
def group_devices(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group display name or object id.")],
    profile: ProfileOption = None,
    direct: DirectOption = False,
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


@entra_app.command("group-members")
def group_members(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group display name or object id.")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Only this kind: user, device, group or servicePrincipal."),
    ] = None,
    profile: ProfileOption = None,
    direct: DirectOption = False,
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


@entra_app.command("user-groups")
def user_groups(
    ctx: typer.Context,
    user: Annotated[str, typer.Argument(help="User principal name, object id or display name.")],
    profile: ProfileOption = None,
    direct: DirectOption = False,
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
        _group_rows(groups),
        {"user": dict(found.raw), "groups": [dict(group.raw) for group in groups]},
    )


@entra_app.command("user-roles")
def user_roles(
    ctx: typer.Context,
    user: Annotated[str, typer.Argument(help="User principal name, object id or display name.")],
    profile: ProfileOption = None,
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


@entra_app.command("sign-ins")
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
        render.note(f"{len(events)} sign-in(s) in the last {format_duration(window)}")


@entra_app.command("app-credentials")
def app_credentials(
    ctx: typer.Context,
    within: Annotated[
        str, typer.Option("--expiring", help="Show credentials ending within this, e.g. 30d.")
    ] = "30d",
    show_all: Annotated[
        bool, typer.Option("--all", help="Show every credential, not only expiring ones.")
    ] = False,
    service_principals: Annotated[
        bool,
        typer.Option(
            "--service-principals",
            help="Include enterprise apps (service principals), e.g. SAML signing certificates.",
        ),
    ] = False,
    include_expired: Annotated[
        bool, typer.Option("--include-expired/--hide-expired", help="Show expired credentials.")
    ] = True,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List app registration secrets and certificates close to expiry.

    Exits 3 when any credential shown is expiring or expired, so a scheduled job can alert.
    """
    window = duration(within) or timedelta(days=30)
    now = datetime.now(UTC)
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    credentials = entra.app_credentials(include_service_principals=service_principals)
    shown = (
        sorted(credentials, key=lambda item: item.ends or now)
        if show_all
        else expiring(credentials, window, now=now, include_expired=include_expired)
    )
    render.emit(
        output,
        ["APP", "KIND", "CREDENTIAL", "ENDS", "DAYS LEFT", "OWNER", "APP ID"],
        [_credential_row(item, now, window) for item in shown],
        [
            {
                "owner_kind": item.owner_kind,
                "owner_name": item.owner_name,
                "owner_id": item.owner_id,
                "app_id": item.app_id,
                "kind": item.kind,
                "credential": dict(item.raw),
                "days_left": item.days_left(now),
            }
            for item in shown
        ],
    )
    attention = [item for item in shown if item.ends is not None and item.ends - now <= window]
    if output is Output.TABLE:
        render.note(
            f"{len(attention)} credential(s) end within {format_duration(window)} "
            f"(of {len(credentials)} checked)"
        )
    if attention:
        raise typer.Exit(ATTENTION)


def _credential_row(item: AppCredential, now: datetime, window: timedelta) -> list[render.Cell]:
    days = item.days_left(now)
    if days is None:
        left: render.Cell = "-"
    elif days < 0:
        left = (f"expired {-days}d ago", "red")
    elif item.ends is not None and item.ends - now <= window:
        left = (str(days), "yellow")
    else:
        left = str(days)
    return [
        item.owner_name,
        item.kind,
        item.name,
        render.when(item.ends),
        left,
        item.owner_kind,
        item.app_id,
    ]


@entra_app.command("ca-policies")
def ca_policies(
    ctx: typer.Context,
    state: Annotated[
        str | None,
        typer.Option("--state", help="Only this state: enabled, disabled or report-only."),
    ] = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List Conditional Access policies: who and what each targets, and what it requires.

    Needs Policy.Read.All, which the Azure CLI's token does not carry: use a profile
    with its own app registration.
    """
    states = {
        "enabled": "enabled",
        "disabled": "disabled",
        "report-only": "enabledForReportingButNotEnforced",
    }
    if state is not None and state not in states:
        raise typer.BadParameter(f"--state must be one of {', '.join(states)}")
    runtime = get_runtime(ctx).microsoft
    entra = runtime.entra(runtime.profile(profile))
    policies = [
        policy for policy in entra.ca_policies() if state is None or policy.state == states[state]
    ]
    state_names = {value: key for key, value in states.items()}
    render.emit(
        output,
        ["POLICY", "STATE", "USERS", "APPS", "GRANT", "SESSION", "MODIFIED"],
        [
            [
                policy.display_name,
                state_names.get(policy.state, policy.state),
                _targets(
                    policy.include_users + policy.include_groups + policy.include_roles,
                    policy.exclude_users + policy.exclude_groups,
                ),
                _targets(policy.include_applications, policy.exclude_applications),
                f" {policy.grant_operator} ".join(policy.grant_controls) or "-",
                ", ".join(policy.session_controls),
                render.when(policy.modified),
            ]
            for policy in policies
        ],
        [dict(policy.raw) for policy in policies],
    )
    if not policies and state is None:
        # Graph answers an unauthorised listing with an empty list rather than an error.
        render.warn(
            "no Conditional Access policies returned; if you expected some, the token may lack "
            "Policy.Read.All, which the Azure CLI's token never has"
        )


def _targets(include: tuple[str, ...], exclude: tuple[str, ...]) -> str:
    """``All`` or ``3 included`` plus ``, 1 excluded``: ids alone mean little in a table."""
    if not include:
        text = "none"
    elif len(include) == 1 and not is_guid(include[0]):
        text = include[0]
    else:
        text = f"{len(include)} included"
    return f"{text}, {len(exclude)} excluded" if exclude else text
