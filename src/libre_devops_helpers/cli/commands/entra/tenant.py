"""Tenant-wide reads: app credentials near their expiry, and Conditional Access policies."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.util import format_duration, is_guid
from libre_devops_helpers.microsoft.entra import (
    AppCredential,
    expiring,
)


def register(app: typer.Typer) -> None:
    """Add ``app-credentials`` and ``ca-policies`` to ``app``."""
    app.command("app-credentials")(app_credentials)
    app.command("ca-policies")(ca_policies)


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
    sort: SortOption = None,
    unique: UniqueOption = None,
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


def ca_policies(
    ctx: typer.Context,
    state: Annotated[
        str | None,
        typer.Option("--state", help="Only this state: enabled, disabled or report-only."),
    ] = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
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
