"""Advanced Hunting: any KQL query, and a device's timeline built from the device tables."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    EndpointOption,
    FromOption,
    OutputOption,
    ProfileOption,
    QueryFileOption,
    ShowQueryOption,
    SinceOption,
    SortOption,
    TodayOption,
    ToOption,
    UniqueOption,
    YesterdayOption,
    get_runtime,
    read_query,
    time_window,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.timewindow import Window, last
from libre_devops_helpers.microsoft.xdr.timeline import (
    DEFAULT_LIMIT,
    MAX_EVENTS,
    Timeline,
    TimelineEvent,
    outside_retention,
    parse_kinds,
    read_timeline,
    timeline_query,
)


def register(app: typer.Typer) -> None:
    """Add ``hunt`` and ``timeline`` to ``app``."""
    app.command("hunt")(hunt)
    app.command("timeline")(timeline)


def hunt(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(
            help="KQL query. Omit, or pass -, to read it from stdin.", show_default=False
        ),
    ] = None,
    file: QueryFileOption = None,
    endpoint: EndpointOption = False,
    timespan: Annotated[
        str | None,
        typer.Option("--timespan", help="How far back the data goes, e.g. 7d. Default: 30 days."),
    ] = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run an Advanced Hunting (KQL) query over Defender XDR.

    Through Microsoft Graph, which covers every Defender XDR table: devices, email,
    identity, cloud apps and alerts. It needs ThreatHunting.Read.All, which the Azure
    CLI's token never has: use an interactive or device-code profile whose app has it,
    or --endpoint for the device tables with the Azure CLI's sign-in.
    """
    text = read_query(query, file)
    if not endpoint:
        from libre_devops_helpers.cli.commands.graph import run_graph_hunt

        run_graph_hunt(ctx, text, timespan, profile, output)
        return
    if timespan:
        raise typer.BadParameter("--timespan is not available with --endpoint; put it in the query")
    runtime = get_runtime(ctx).microsoft
    result = runtime.xdr(runtime.profile(profile)).hunt(text)
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")


def timeline(
    ctx: typer.Context,
    device: Annotated[
        str, typer.Argument(help="The device: its FQDN, or its host name.", show_default=False)
    ],
    kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            help="Only these kinds of event: process, network, file, registry, logon, "
            "image-load, other or alert. Comma-separated or repeated. Default: all.",
            show_default=False,
        ),
    ] = None,
    today: TodayOption = False,
    yesterday: YesterdayOption = False,
    since: SinceOption = None,
    start: FromOption = None,
    end: ToOption = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=MAX_EVENTS, help="At most this many, the newest."),
    ] = DEFAULT_LIMIT,
    endpoint: EndpointOption = False,
    show_query: ShowQueryOption = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A device's timeline: its events, newest first, from Advanced Hunting.

    Defender has no API for the portal's device timeline, so this asks Advanced Hunting's
    device tables for the same events: processes, network connections, files, registry,
    logons, image loads, other device events and alerts. Advanced Hunting keeps 30 days;
    the portal reaches further back. Through Graph like 'xdr hunt', or --endpoint, which
    has the device tables but not the alert ones, so no alerts. The default is the last 24
    hours and the newest 1000 events. Times show in local time;
    -o json has them in UTC.
    """
    window = time_window(
        today, yesterday, since, start, end, lambda now: last(timedelta(hours=24), now)
    )
    chosen = parse_kinds(kinds or [], device_tables_only=endpoint)
    query = timeline_query(device, window, chosen, limit)
    if show_query:
        render.echo(query)
        return
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    result = runtime.xdr(selected).hunt(query) if endpoint else runtime.graph(selected).hunt(query)
    found = read_timeline(device, result, limit)
    render.emit(
        output,
        ["TIME", "TYPE", "ACTION", "ACCOUNT", "PROCESS", "DETAIL"],
        [_event_row(event) for event in found.events],
        [_event_record(event) for event in found.events],
    )
    render.note(
        f"{len(found.events)} event(s) on {device}, {window.label} (profile {selected.name})"
    )
    if endpoint and not kinds:
        render.note("alerts are left out: the Defender for Endpoint API has no alert tables")
    for warning in _timeline_warnings(found, window):
        render.warn(warning)


def _event_row(event: TimelineEvent) -> list[render.Cell]:
    kind: render.Cell = (event.kind, "red") if event.kind == "alert" else event.kind
    return [
        render.moment(event.time),
        kind,
        event.action,
        event.account,
        event.process,
        event.detail,
    ]


def _event_record(event: TimelineEvent) -> dict[str, Any]:
    return {
        "time": event.time.isoformat() if event.time else None,
        "type": event.kind,
        "action": event.action,
        "detail": event.detail,
        "account": event.account,
        "process": event.process,
        "device_name": event.device_name,
        "device_id": event.device_id,
        "id": event.id,
    }


def _timeline_warnings(found: Timeline, window: Window) -> list[str]:
    """What the person should know about what came back: a cut-off, a shared name, and
    time outside what Advanced Hunting keeps."""
    warnings = []
    if found.truncated:
        warnings.append(
            f"stopped at the newest {found.limit}: narrow the window or --type, or raise --limit"
        )
    if len(found.devices) > 1:
        warnings.append(
            f"{len(found.devices)} devices have that name: {', '.join(found.devices)}; "
            "-o json tells their events apart"
        )
    if outside_retention(window, datetime.now(UTC)):
        warnings.append(
            "Advanced Hunting keeps 30 days of device events, so nothing older is here "
            "(the portal's timeline reaches further back)"
        )
    return warnings
