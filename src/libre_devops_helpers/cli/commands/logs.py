"""Log Analytics commands: run KQL against a workspace, and see which tables it receives."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    QueryFileOption,
    SortOption,
    UniqueOption,
    duration,
    get_runtime,
    read_query,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.core.util import format_duration, format_span
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.loganalytics import (
    DEFAULT_QUIET_AFTER,
    DEFAULT_WINDOW,
    TableIngestion,
    by_quietest,
    ingestion_query,
    read_ingestion,
)
from libre_devops_helpers.microsoft.workspaces import workspace_ref

logs_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Log Analytics and Sentinel workspaces: run KQL, and see which tables are receiving data.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    str | None,
    typer.Option(
        "--workspace",
        "-w",
        help="The workspace: its Workspace ID (the GUID on its Overview page), its resource "
        "id (/subscriptions/.../workspaces/NAME), or its name. A resource id or a name is "
        "looked up in Resource Manager, which needs Reader on it. Default: the profile's "
        "workspace.",
        show_default=False,
    ),
]


def register(app: typer.Typer) -> None:
    """Add the ``logs`` commands to ``app``."""
    app.add_typer(logs_app, name="logs")


@logs_app.command("query")
def query(
    ctx: typer.Context,
    text: Annotated[
        str | None,
        typer.Argument(
            metavar="[QUERY]",
            help="KQL query. Omit, or pass -, to read it from stdin.",
            show_default=False,
        ),
    ] = None,
    file: QueryFileOption = None,
    workspace: WorkspaceOption = None,
    timespan: Annotated[
        str | None,
        typer.Option("--timespan", help="Bound the query to this long ago, e.g. 24h, 7d."),
    ] = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run a KQL query against a Log Analytics (or Sentinel) workspace."""
    kql = read_query(text, file)
    window = duration(timespan)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    workspace_id = _workspace(workspace, runtime, selected)
    result = runtime.logs(selected).query(workspace_id, kql, timespan=window)
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")


@logs_app.command("ingestion")
def ingestion(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    window: Annotated[
        str, typer.Option("--window", help="How far back to look, e.g. 7d, 90d.")
    ] = "30d",
    quiet_after: Annotated[
        str,
        typer.Option("--quiet-after", help="Flag a table that received nothing for this long."),
    ] = "24h",
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Which tables the workspace is receiving: when each last got data, and how much.

    Read from the Usage table, so it is cheap and accurate to the hour; a table that got
    nothing in the whole window is not listed, since nothing says it exists. Quiet tables
    come first. Exits 3 when any table has been quiet for longer than --quiet-after.
    """
    span = duration(window) or DEFAULT_WINDOW
    after = duration(quiet_after) or DEFAULT_QUIET_AFTER
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    workspace_id = _workspace(workspace, runtime, selected)
    result = runtime.logs(selected).query(workspace_id, ingestion_query(span))
    now = datetime.now(UTC)
    tables = by_quietest(read_ingestion(result), now, after)
    render.emit(
        output,
        ["TABLE", "LAST DATA", "QUIET FOR", "GB", "BILLABLE GB", "SOLUTIONS"],
        [_ingestion_row(table, now, after) for table in tables],
        [_ingestion_record(table, now, after) for table in tables],
    )
    quiet = sum(1 for table in tables if table.quiet(now, after))
    total = sum(table.gigabytes for table in tables)
    billable = sum(table.billable_gigabytes for table in tables)
    render.note(
        f"{len(tables)} table(s) received data in the last {format_span(span)}: "
        f"{total:,.2f} GB, {billable:,.2f} GB billable (workspace {workspace_id})"
    )
    for warning in result.warnings:
        render.warn(warning)
    if quiet:
        render.warn(f"{quiet} table(s) quiet for over {format_span(after)}")
        raise typer.Exit(ATTENTION)


def _workspace(given: str | None, runtime: MicrosoftRuntime, selected: Profile) -> str:
    """The Workspace ID to ask: --workspace's, else the profile's. A resource id or a name is
    looked up, and what it named is noted, so it is plain which workspace was read."""
    named = given or selected.workspace or selected.workspace_id
    if not named:
        raise ConfigError(
            "no workspace given",
            hint="pass --workspace, or set workspace on the profile",
        )
    ref = workspace_ref(named)
    if ref.kind == "workspace id":
        return ref.value
    found = runtime.azure(selected).workspace(ref)
    render.note(
        f"workspace {found.name} in {found.resource_group or '-'}, from its {ref.kind}: "
        f"Workspace ID {found.workspace_id}"
    )
    return found.workspace_id


def _ingestion_row(table: TableIngestion, now: datetime, after: timedelta) -> list[render.Cell]:
    silence = table.quiet_for(now)
    shown = format_duration(silence) if silence is not None else "-"
    quiet: render.Cell = (shown, "red") if table.quiet(now, after) else shown
    return [
        table.table,
        render.when(table.last_data, now=now),
        quiet,
        f"{table.gigabytes:,.3f}",
        f"{table.billable_gigabytes:,.3f}",
        ", ".join(table.solutions),
    ]


def _ingestion_record(table: TableIngestion, now: datetime, after: timedelta) -> dict[str, Any]:
    silence = table.quiet_for(now)
    return {
        "table": table.table,
        "last_data": table.last_data.isoformat() if table.last_data else None,
        "quiet_seconds": int(silence.total_seconds()) if silence is not None else None,
        "quiet": table.quiet(now, after),
        "gigabytes": round(table.gigabytes, 6),
        "billable_gigabytes": round(table.billable_gigabytes, 6),
        "solutions": list(table.solutions),
    }
