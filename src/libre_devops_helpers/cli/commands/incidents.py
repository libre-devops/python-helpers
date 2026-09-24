"""Incident commands: Defender XDR's incident queue, Sentinel's incidents included.

``top`` is today's open incidents, most severe first; ``latest`` the newest of any
status; ``list`` everything in a window; ``summary`` the counts; ``show`` one incident.
Every one takes the same window (``--today``, ``--yesterday``, ``--since``, or
``--from`` and ``--to``, both days whole) and filters.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import OutputOption, ProfileOption, duration, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.timewindow import Window, choose_window, last, today_window
from libre_devops_helpers.microsoft.incidents import (
    OPEN_STATUSES,
    Incident,
    most_severe,
    newest,
    severities_from,
    summarise,
)

incidents_app = typer.Typer(
    name="incidents",
    help="Defender XDR incidents, Sentinel's included: top, latest, list, summary, show.",
    no_args_is_help=True,
)

# What people type, and Graph's values.
STATUS_NAMES = {
    "active": ("active",),
    "in-progress": ("inProgress",),
    "awaiting-action": ("awaitingAction",),
    "resolved": ("resolved",),
    "redirected": ("redirected",),
    "open": OPEN_STATUSES,
    "all": (),
}
SOURCE_NAMES = {
    "sentinel": "microsoftSentinel",
    "endpoint": "microsoftDefenderForEndpoint",
    "identity": "microsoftDefenderForIdentity",
    "office": "microsoftDefenderForOffice365",
    "cloud-apps": "microsoftDefenderForCloudApps",
    "cloud": "microsoftDefenderForCloud",
    "xdr": "microsoft365Defender",
    "entra": "azureAdIdentityProtection",
    "app-governance": "microsoftAppGovernance",
    "dlp": "dataLossPrevention",
    "insider-risk": "microsoftInsiderRiskManagement",
}
_SEVERITY_COLOURS = {"high": "red", "medium": "yellow", "low": "cyan"}
_STATUS_LABELS = {"inProgress": "in progress", "awaitingAction": "awaiting action"}


def register(app: typer.Typer) -> None:
    app.add_typer(incidents_app)


TodayOption = Annotated[bool, typer.Option("--today", help="Since midnight, local time.")]
YesterdayOption = Annotated[bool, typer.Option("--yesterday", help="The whole of yesterday.")]
SinceOption = Annotated[
    str | None, typer.Option("--since", help="The last span of time, e.g. 6h, 7d.")
]
FromOption = Annotated[
    str | None,
    typer.Option("--from", help="From this day (YYYY-MM-DD, today or yesterday), whole."),
]
ToOption = Annotated[
    str | None, typer.Option("--to", help="Up to and including this day (YYYY-MM-DD).")
]
UpdatedOption = Annotated[
    bool,
    typer.Option("--updated", help="Window on when incidents were last updated, not created."),
]
StatusOption = Annotated[
    list[str] | None,
    typer.Option(
        "--status",
        help="open, active, in-progress, awaiting-action, resolved, redirected or all. Repeatable.",
        show_default=False,
    ),
]
SeverityOption = Annotated[
    str | None,
    typer.Option("--severity", help="At least this severity: informational, low, medium, high."),
]
SourceOption = Annotated[
    list[str] | None,
    typer.Option(
        "--source",
        help=f"Only incidents with alerts from here: {', '.join(SOURCE_NAMES)}. Repeatable.",
        show_default=False,
    ),
]
LimitOption = Annotated[int | None, typer.Option("--limit", "-n", min=1, help="Most to show.")]


@incidents_app.command("top")
def top(
    ctx: typer.Context,
    today: TodayOption = False,
    yesterday: YesterdayOption = False,
    since: SinceOption = None,
    start: FromOption = None,
    end: ToOption = None,
    updated: UpdatedOption = False,
    status: StatusOption = None,
    severity: SeverityOption = None,
    source: SourceOption = None,
    limit: LimitOption = 10,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The most severe open incidents, today unless told otherwise: 10 by default."""
    _show_list(
        ctx,
        _window(today, yesterday, since, start, end, today_window),
        updated=updated,
        statuses=status or ["open"],
        severity=severity,
        sources=source,
        limit=limit,
        order=most_severe,
        profile=profile,
        output=output,
    )


@incidents_app.command("latest")
def latest(
    ctx: typer.Context,
    today: TodayOption = False,
    yesterday: YesterdayOption = False,
    since: SinceOption = None,
    start: FromOption = None,
    end: ToOption = None,
    updated: UpdatedOption = False,
    status: StatusOption = None,
    severity: SeverityOption = None,
    source: SourceOption = None,
    limit: LimitOption = 10,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The newest incidents of any status, from the last 30 days: 10 by default."""
    _show_list(
        ctx,
        _window(today, yesterday, since, start, end, lambda now: last(timedelta(days=30), now)),
        updated=updated,
        statuses=status or ["all"],
        severity=severity,
        sources=source,
        limit=limit,
        order=newest,
        profile=profile,
        output=output,
    )


@incidents_app.command("list")
def list_incidents(
    ctx: typer.Context,
    today: TodayOption = False,
    yesterday: YesterdayOption = False,
    since: SinceOption = None,
    start: FromOption = None,
    end: ToOption = None,
    updated: UpdatedOption = False,
    status: StatusOption = None,
    severity: SeverityOption = None,
    source: SourceOption = None,
    limit: LimitOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Every incident in a window, newest first: the last 24 hours by default.

    For between days, give --from and --to: ldo xdr incidents list --from 2026-09-01
    --to 2026-09-24 takes both days whole.
    """
    _show_list(
        ctx,
        _window(today, yesterday, since, start, end, lambda now: last(timedelta(hours=24), now)),
        updated=updated,
        statuses=status or ["all"],
        severity=severity,
        sources=source,
        limit=limit,
        order=newest,
        profile=profile,
        output=output,
    )


@incidents_app.command("summary")
def summary(
    ctx: typer.Context,
    today: TodayOption = False,
    yesterday: YesterdayOption = False,
    since: SinceOption = None,
    start: FromOption = None,
    end: ToOption = None,
    updated: UpdatedOption = False,
    status: StatusOption = None,
    severity: SeverityOption = None,
    source: SourceOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """How many incidents, by severity, status and source: today by default."""
    window = _window(today, yesterday, since, start, end, today_window)
    found = _fetch(ctx, window, updated, status or ["all"], severity, source, profile)
    counts = summarise(found.incidents)
    if output is not Output.TABLE:
        rows = [
            *(["severity", name, str(count)] for name, count in counts.by_severity.items()),
            *(["status", name, str(count)] for name, count in counts.by_status.items()),
            *(["source", name, str(count)] for name, count in counts.by_source.items()),
        ]
        render.emit(
            output,
            ["BY", "VALUE", "INCIDENTS"],
            rows,
            {
                "window": window.label,
                "total": counts.total,
                "by_severity": counts.by_severity,
                "by_status": counts.by_status,
                "by_source": counts.by_source,
            },
        )
        return
    render.echo(render.title(f"{counts.total} incident(s) {window.label}"))
    for heading, values, colour in (
        ("SEVERITY", counts.by_severity, _SEVERITY_COLOURS),
        ("STATUS", {_status(name): n for name, n in counts.by_status.items()}, {}),
        ("SOURCE", counts.by_source, {}),
    ):
        if values:
            render.echo()
            render.echo(
                render.table(
                    [heading, "INCIDENTS"],
                    [[(name, colour.get(name)), str(n)] for name, n in values.items()],
                )
            )
    _warn_truncated(found.truncated)


@incidents_app.command("show")
def show(
    ctx: typer.Context,
    incident_id: Annotated[str, typer.Argument(metavar="ID", help="The incident's number.")],
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """One incident: its alerts, where they came from, the devices and users involved."""
    runtime = get_runtime(ctx).microsoft
    incident = runtime.incidents(runtime.profile(profile)).incident(incident_id)
    if output is not Output.TABLE:
        render.emit(
            output,
            ["CREATED", "SEVERITY", "SOURCE", "TITLE", "ALERT ID"],
            [
                [
                    render.when(alert.created),
                    alert.severity,
                    alert.source_name,
                    alert.title,
                    alert.id,
                ]
                for alert in incident.alerts
            ],
            dict(incident.raw),
        )
        return
    render.echo(render.title(f"Incident {incident.id}: {incident.title}"))
    render.echo(
        render.pairs(
            [
                ("Severity", incident.severity),
                ("Status", _status(incident.status)),
                ("Created", render.when(incident.created)),
                ("Updated", render.when(incident.updated)),
                ("Assigned to", incident.assigned_to or "(nobody)"),
                ("Classification", incident.classification or "-"),
                ("Determination", incident.determination or "-"),
                ("Sources", ", ".join(incident.source_names) or "-"),
                ("Devices", ", ".join(incident.devices) or "-"),
                ("Users", ", ".join(incident.users) or "-"),
                ("Tags", ", ".join(incident.tags) or "-"),
                ("Link", incident.web_url or "-"),
            ]
        )
    )
    if incident.alerts:
        render.echo()
        render.echo(
            render.table(
                ["CREATED", "SEVERITY", "STATUS", "SOURCE", "TITLE"],
                [
                    [
                        render.when(alert.created),
                        (alert.severity, _SEVERITY_COLOURS.get(alert.severity.lower())),
                        alert.status,
                        alert.source_name,
                        alert.title,
                    ]
                    for alert in incident.alerts
                ],
            )
        )


# Shared -------------------------------------------------------------------------------


def _window(
    today: bool,
    yesterday: bool,
    since: str | None,
    start: str | None,
    end: str | None,
    default: Callable[[datetime], Window],
) -> Window:
    return choose_window(
        today=today,
        yesterday=yesterday,
        since=duration(since),
        start_day=start,
        end_day=end,
        default=default,
    )


def _fetch(
    ctx: typer.Context,
    window: Window,
    updated: bool,
    statuses: list[str],
    severity: str | None,
    sources: list[str] | None,
    profile: str | None,
):
    wanted_statuses: list[str] = []
    for name in statuses:
        key = name.strip().lower()
        if key not in STATUS_NAMES:
            raise typer.BadParameter(f"--status must be one of {', '.join(STATUS_NAMES)}")
        wanted_statuses.extend(STATUS_NAMES[key])
    wanted_sources: list[str] = []
    for name in sources or ():
        key = name.strip().lower()
        if key not in SOURCE_NAMES:
            raise typer.BadParameter(f"--source must be one of {', '.join(SOURCE_NAMES)}")
        wanted_sources.append(SOURCE_NAMES[key])
    runtime = get_runtime(ctx).microsoft
    return runtime.incidents(runtime.profile(profile)).incidents(
        start=window.start,
        end=window.end,
        by="lastUpdateDateTime" if updated else "createdDateTime",
        statuses=tuple(dict.fromkeys(wanted_statuses)),
        severities=severities_from(severity) if severity else (),
        sources=tuple(wanted_sources),
    )


def _show_list(
    ctx: typer.Context,
    window: Window,
    *,
    updated: bool,
    statuses: list[str],
    severity: str | None,
    sources: list[str] | None,
    limit: int | None,
    order: Callable[[tuple[Incident, ...]], list[Incident]],
    profile: str | None,
    output: Output,
) -> None:
    found = _fetch(ctx, window, updated, statuses, severity, sources, profile)
    ordered = order(found.incidents)
    shown = ordered[:limit] if limit else ordered
    render.emit(
        output,
        ["CREATED", "SEVERITY", "STATUS", "ID", "TITLE", "SOURCES", "ALERTS", "ASSIGNED"],
        [
            [
                render.when(incident.created),
                (incident.severity, _SEVERITY_COLOURS.get(incident.severity.lower())),
                _status(incident.status),
                incident.id,
                incident.title,
                ", ".join(incident.source_names),
                str(len(incident.alerts)),
                incident.assigned_to,
            ]
            for incident in shown
        ],
        [dict(incident.raw) for incident in shown],
    )
    what = "updated" if updated else "created"
    render.note(f"{len(shown)} of {len(ordered)} incident(s) {what} {window.label}")
    _warn_truncated(found.truncated)


def _status(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


def _warn_truncated(truncated: bool) -> None:
    if truncated:
        render.warn("stopped at the incident limit; narrow the window to see them all")
