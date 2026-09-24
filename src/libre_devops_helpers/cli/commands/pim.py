"""PIM commands: eligible and active roles, requests, approvals and role settings.

Each command covers three areas: Azure resource roles (ARM), Entra roles and PIM for
Groups (Graph). An area that cannot be read (no P2 licence, a token without the scope) is
reported as a warning and the others still show; the command fails only when every area
it was asked for fails.
"""

import re
from collections.abc import Callable
from typing import Annotated, TypeVar

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ERROR
from libre_devops_helpers.cli.options import OutputOption, ProfileOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.util import is_guid
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.pim import AREAS, Area, PimAssignment, PimRequest

T = TypeVar("T")

pim_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Privileged Identity Management: eligible and active roles, requests, approvals.",
    no_args_is_help=True,
)

AzureOption = Annotated[bool, typer.Option("--azure", help="Azure resource roles.")]
EntraOption = Annotated[bool, typer.Option("--entra", help="Entra (directory) roles.")]
GroupsOption = Annotated[bool, typer.Option("--groups", help="PIM for Groups.")]
UserOption = Annotated[
    str | None,
    typer.Option(
        "--user",
        "-u",
        help="Someone else's (UPN, name or object id). Default: the signed-in user.",
        show_default=False,
    ),
]
SubscriptionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--subscription",
        "-s",
        help="With --user: subscriptions to search for Azure roles. Default: all in the tenant.",
        show_default=False,
    ),
]


def register(app: typer.Typer) -> None:
    app.add_typer(pim_app, name="pim")


def _areas(azure: bool, entra: bool, groups: bool) -> list[Area]:
    chosen = [area for area, wanted in zip(AREAS, (azure, entra, groups), strict=True) if wanted]
    return chosen or list(AREAS)


def _gather(areas: list[Area], calls: dict[Area, Callable[[], list[T]]]) -> list[T]:
    """Run each area's call; warn about the ones that fail, and fail only if all do."""
    found: list[T] = []
    failed = 0
    for area in areas:
        try:
            found.extend(calls[area]())
        except LdoError as exc:
            failed += 1
            render.warn(f"{area}: {exc}")
            hint = _hint(area, str(exc)) or exc.hint
            if hint:
                render.note(f"hint: {hint}")
    if failed and failed == len(areas):
        raise typer.Exit(ERROR)
    return found


def _hint(area: Area, text: str) -> str | None:
    if "AadPremiumLicenseRequired" in text or "TenantNotOnboarded" in text:
        return "PIM needs Microsoft Entra ID P2 or ID Governance in the tenant"
    if area != "azure" and ("PermissionScopeNotGranted" in text or "HTTP 403" in text):
        return (
            "these views need a token with the PIM scopes; the Azure CLI's never has them. Use a "
            'profile with auth = "interactive" or "device-code" '
            f"(see {brand.docs('authentication')})"
        )
    return None


def _principal(runtime: MicrosoftRuntime, profile: Profile, user: str | None) -> str | None:
    if user is None:
        return None
    if is_guid(user):
        return user.strip().lower()
    return runtime.entra(profile).find_principal(user).id


def _scopes(runtime: MicrosoftRuntime, profile: Profile, chosen: list[str] | None) -> list[str]:
    return [f"/subscriptions/{item}" for item in runtime.subscription_ids(profile, chosen)]


def _duration(value: str) -> str:
    """ISO 8601 durations as people say them: PT8H -> 8h, P1DT2H -> 1d 2h."""
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not value or not match or not any(match.groups()):
        return value or "-"
    return " ".join(f"{n}{unit}" for n, unit in zip(match.groups(), "dhms", strict=True) if n)


def _assignment_rows(items: list[PimAssignment], active: bool) -> list[list[render.Cell]]:
    rows: list[list[render.Cell]] = []
    for item in items:
        ends: render.Cell = (
            ("permanent", "yellow") if item.permanent and active else render.when(item.ends)
        )
        row: list[render.Cell] = [item.area, item.role, item.scope, item.member_type or "-"]
        if active:
            row.append(("activated", "green") if item.activated else item.assignment_type or "-")
        rows.extend([[*row, render.when(item.starts), ends]])
    return rows


def _assignment_records(items: list[PimAssignment]) -> list[dict[str, object]]:
    return [
        {
            "area": item.area,
            "role": item.role,
            "scope": item.scope,
            "member_type": item.member_type,
            "assignment_type": item.assignment_type,
            "permanent": item.permanent,
            "raw": dict(item.raw),
        }
        for item in items
    ]


@pim_app.command("eligible")
def eligible(
    ctx: typer.Context,
    azure: AzureOption = False,
    entra: EntraOption = False,
    groups: GroupsOption = False,
    user: UserOption = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the roles you (or --user) can activate through PIM."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    principal = _principal(runtime, selected, user)
    areas = _areas(azure, entra, groups)
    items = _gather(
        areas,
        {
            "azure": lambda: runtime.azure_pim(selected).eligible(
                principal_id=principal,
                scopes=_scopes(runtime, selected, subscription) if principal else (),
            ),
            "entra": lambda: runtime.graph_pim(selected).role_eligible(principal_id=principal),
            "groups": lambda: runtime.graph_pim(selected).group_eligible(principal_id=principal),
        },
    )
    render.emit(
        output,
        ["AREA", "ROLE", "SCOPE", "MEMBERSHIP", "FROM", "UNTIL"],
        _assignment_rows(items, active=False),
        _assignment_records(items),
    )
    render.note(f"{len(items)} eligible role(s)")


@pim_app.command("active")
def active(
    ctx: typer.Context,
    azure: AzureOption = False,
    entra: EntraOption = False,
    groups: GroupsOption = False,
    user: UserOption = None,
    subscription: SubscriptionOption = None,
    permanent_only: Annotated[
        bool,
        typer.Option("--permanent-only", help="Only standing access: roles with no end date."),
    ] = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the roles you (or --user) hold now: activated through PIM, or permanent."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    principal = _principal(runtime, selected, user)
    items = _gather(
        _areas(azure, entra, groups),
        {
            "azure": lambda: runtime.azure_pim(selected).active(
                principal_id=principal,
                scopes=_scopes(runtime, selected, subscription) if principal else (),
            ),
            "entra": lambda: runtime.graph_pim(selected).role_active(principal_id=principal),
            "groups": lambda: runtime.graph_pim(selected).group_active(principal_id=principal),
        },
    )
    if permanent_only:
        items = [item for item in items if item.permanent]
    render.emit(
        output,
        ["AREA", "ROLE", "SCOPE", "MEMBERSHIP", "TYPE", "FROM", "UNTIL"],
        _assignment_rows(items, active=True),
        _assignment_records(items),
    )
    standing = sum(1 for item in items if item.permanent)
    render.note(f"{len(items)} active role(s), {standing} of them permanent")


def _request_rows(items: list[PimRequest]) -> list[list[render.Cell]]:
    colours = {"pendingapproval": "yellow", "denied": "red", "provisioned": "green"}
    return [
        [
            item.area,
            render.when(item.created),
            item.action,
            (item.status, colours.get(item.status.casefold())),
            item.role,
            item.scope,
            _duration(item.duration) if item.duration else render.when(item.ends),
            item.justification,
        ]
        for item in items
    ]


def _request_records(items: list[PimRequest]) -> list[dict[str, object]]:
    return [
        {"area": item.area, "status": item.status, "role": item.role, "raw": dict(item.raw)}
        for item in items
    ]


_REQUEST_HEADERS = ["AREA", "CREATED", "ACTION", "STATUS", "ROLE", "SCOPE", "FOR", "JUSTIFICATION"]


@pim_app.command("requests")
def requests_(
    ctx: typer.Context,
    azure: AzureOption = False,
    entra: EntraOption = False,
    groups: GroupsOption = False,
    user: UserOption = None,
    subscription: SubscriptionOption = None,
    pending: Annotated[
        bool, typer.Option("--pending", help="Only requests still waiting.")
    ] = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List PIM requests you (or --user) made, newest first, and where each has got to."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    principal = _principal(runtime, selected, user)
    items = _gather(
        _areas(azure, entra, groups),
        {
            "azure": lambda: runtime.azure_pim(selected).requests(
                principal_id=principal,
                scopes=_scopes(runtime, selected, subscription) if principal else (),
            ),
            "entra": lambda: runtime.graph_pim(selected).role_requests(principal_id=principal),
            "groups": lambda: runtime.graph_pim(selected).group_requests(principal_id=principal),
        },
    )
    if pending:
        items = [item for item in items if item.pending]
    render.emit(output, _REQUEST_HEADERS, _request_rows(items), _request_records(items))
    render.note(f"{len(items)} request(s)")


@pim_app.command("approvals")
def approvals(
    ctx: typer.Context,
    azure: AzureOption = False,
    entra: EntraOption = False,
    groups: GroupsOption = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List PIM requests waiting for you to approve them."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    items = _gather(
        _areas(azure, entra, groups),
        {
            "azure": lambda: runtime.azure_pim(selected).requests(approver=True),
            "entra": lambda: runtime.graph_pim(selected).role_requests(approver=True),
            "groups": lambda: runtime.graph_pim(selected).group_requests(approver=True),
        },
    )
    items = [item for item in items if item.pending]
    render.emit(output, _REQUEST_HEADERS, _request_rows(items), _request_records(items))
    render.note(
        f"{len(items)} request(s) waiting for you; approve them in the portal or with "
        f"your usual tooling ({brand.COMMAND} only reads)"
    )


@pim_app.command("settings")
def settings(
    ctx: typer.Context,
    role: Annotated[
        str | None,
        typer.Argument(help="Role name, e.g. Owner or 'Global Administrator'.", show_default=False),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option(
            "--scope",
            help="An Azure scope, e.g. /subscriptions/SUBSCRIPTION_ID, for an Azure role.",
        ),
    ] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="A PIM for Groups group (name or object id).")
    ] = None,
    owner: Annotated[
        bool, typer.Option("--owner", help="With --group: the owner settings.")
    ] = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Show what activating a role takes: duration, MFA, justification, approval, approvers.

    An Azure role needs --scope; an Entra role needs only its name; a group needs --group.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    area: Area = "groups" if group else "azure" if scope else "entra"
    try:
        if group:
            group_id = group if is_guid(group) else runtime.entra(selected).get_group(group).id
            found = runtime.graph_pim(selected).group_settings(
                group_id, "owner" if owner else "member"
            )
        elif role is None:
            raise typer.BadParameter("name a role, or pass --group")
        elif scope:
            found = runtime.azure_pim(selected).settings(role, scope)
        else:
            found = runtime.graph_pim(selected).role_settings(role)
    except LdoError as exc:
        raise LdoError(str(exc), hint=_hint(area, str(exc)) or exc.hint) from None
    pairs = [
        ("Role", found.role),
        ("Area", found.area),
        ("Scope", found.scope),
        ("Longest activation", _duration(found.max_activation)),
        ("Needs MFA", render.yes_no(found.requires_mfa)),
        ("Needs justification", render.yes_no(found.requires_justification)),
        ("Needs a ticket", render.yes_no(found.requires_ticket)),
        ("Needs approval", render.yes_no(found.requires_approval)),
        ("Approvers", ", ".join(found.approvers)),
        ("Authentication context", found.authentication_context),
        ("Eligible assignments", _duration(found.eligible_expiry)),
        ("Active assignments", _duration(found.active_expiry)),
    ]
    if output is Output.TABLE:
        render.echo(render.pairs(pairs))
    else:
        render.emit(
            output,
            [label for label, _ in pairs],
            [[value for _, value in pairs]],
            {
                **{label: value for label, value in pairs},
                "rules": [dict(rule) for rule in found.raw],
            },
        )
