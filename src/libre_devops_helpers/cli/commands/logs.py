"""Log Analytics commands: run KQL against a workspace."""

from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    QueryFileOption,
    duration,
    get_runtime,
    read_query,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import ConfigError

logs_app = typer.Typer(
    rich_markup_mode="markdown", help="Log Analytics and Sentinel: run KQL.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
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
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace ID (a GUID). Default: the profile's workspace_id.",
            show_default=False,
        ),
    ] = None,
    timespan: Annotated[
        str | None,
        typer.Option("--timespan", help="Bound the query to this long ago, e.g. 24h, 7d."),
    ] = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run a KQL query against a Log Analytics (or Sentinel) workspace."""
    kql = read_query(text, file)
    window = duration(timespan)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    workspace_id = workspace or selected.workspace_id
    if not workspace_id:
        raise ConfigError(
            "no workspace given",
            hint="pass --workspace, or set workspace_id on the profile",
        )
    result = runtime.logs(selected).query(workspace_id, kql, timespan=window)
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")
