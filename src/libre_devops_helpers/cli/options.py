"""Options shared by several commands, and access to the per-invocation Runtime."""

import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import InputError, LdoError
from libre_devops_helpers.core.inputs import read_names
from libre_devops_helpers.core.timewindow import Window, choose_window
from libre_devops_helpers.core.util import parse_duration
from libre_devops_helpers.microsoft.config import load_config


def get_runtime(ctx: typer.Context) -> Runtime:
    """The Runtime the root command stored on the context."""
    runtime = ctx.find_object(Runtime)
    if runtime is None:
        raise RuntimeError("the CLI runtime was not initialised")
    return runtime


def complete_profile(incomplete: str) -> list[str]:
    """Shell completion for profile names. Silent when there is no usable config."""
    try:
        names = load_config().profiles
    except LdoError:
        return []
    return [name for name in sorted(names) if name.startswith(incomplete)]


def duration(value: str | None) -> timedelta | None:
    """Parse a duration option (``15m``, ``2h``, ``7d``), reporting a bad one as usage."""
    if value is None:
        return None
    try:
        return parse_duration(value)
    except InputError as exc:
        raise typer.BadParameter(str(exc)) from None


def names(
    values: list[str] | None,
    from_file: Path | None,
    column: str | None,
    sheet: str | None = None,
) -> list[str]:
    """Names from arguments, ``-`` for stdin, and ``--from-file``; at least one is needed."""
    found = read_names(
        values or [], stdin=sys.stdin, from_file=from_file, column=column, sheet=sheet
    )
    if not found:
        raise InputError("no names given", hint="pass names, '-' for stdin, or --from-file")
    return found


def read_query(query: str | None, file: Path | None) -> str:
    """A query from the argument, from ``--file``, or from stdin, in that order."""
    if query and query != "-":
        return query
    if file is not None:
        try:
            return file.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputError(f"cannot read {file}: {exc}") from None
    if query == "-" or not sys.stdin.isatty():
        text = sys.stdin.read()
        if text.strip():
            return text
    raise InputError("no query given", hint="pass it as an argument, with --file, or on stdin")


ProfileOption = Annotated[
    str | None,
    typer.Option(
        "--profile",
        "-p",
        envvar=brand.PROFILE_ENV,
        help="Profile from the config file. Default: default_profile, else the az active account.",
        autocompletion=complete_profile,
        show_default=False,
    ),
]

OutputOption = Annotated[
    Output,
    typer.Option(
        "--output",
        "-o",
        help="table for people, json for scripts, csv for spreadsheets, tsv for shell "
        "pipelines (no header, as az -o tsv).",
    ),
]

# --sort and --unique never reach the command they are on: each hands its value to
# cli.render as it is parsed (callback, and expose_value=False), and render.emit arranges
# the rows from there. So a command lists them in its signature, to offer them, and never
# uses them in its body. They belong on commands that write a list, not one record.
SortOption = Annotated[
    list[str] | None,
    typer.Option(
        "--sort",
        help="Sort the rows by a column, named as in the table; add :desc to reverse it. "
        "Repeat it to sort by more, most significant first. Numbers, versions, severities "
        "and dates sort as such. Table, CSV and TSV.",
        callback=render.sort_rows,
        expose_value=False,
        show_default=False,
    ),
]

UniqueOption = Annotated[
    list[str] | None,
    typer.Option(
        "--unique",
        help="Keep only the first row for each value of a column, ignoring case; repeat it "
        "for each combination of several. After --sort, so sorting newest first keeps the "
        "newest.",
        callback=render.unique_rows,
        expose_value=False,
        show_default=False,
    ),
]

NamesArgument = Annotated[
    list[str] | None,
    typer.Argument(
        help='Names: "a,b,c", several arguments, or - to read stdin.', show_default=False
    ),
]

FromFileOption = Annotated[
    Path | None,
    typer.Option(
        "--from-file",
        "-f",
        help=(
            "Read names from a file: one per line, or a column of a CSV or Excel workbook "
            "(.xlsx, .xlsm, .xltx, .xltm; see --column and --sheet)."
        ),
        dir_okay=False,
        exists=True,
        show_default=False,
    ),
]

ColumnOption = Annotated[
    str | None,
    typer.Option(
        "--column",
        help="Column holding the names, matched by header. Title rows above it are skipped.",
    ),
]

SheetOption = Annotated[
    str | None,
    typer.Option(
        "--sheet",
        help=(
            "Workbook sheet (tab) to read. Default: the one visible sheet with --column, "
            "or the first visible sheet."
        ),
        show_default=False,
    ),
]

QueryFileOption = Annotated[
    Path | None,
    typer.Option("--file", help="Read the query from a file.", dir_okay=False, exists=True),
]

DirectOption = Annotated[
    bool,
    typer.Option("--direct", help="Direct memberships only. Default includes nested groups."),
]


# Advanced Hunting goes through Graph by default; this sends it to Defender for Endpoint's
# own API, which the Azure CLI's sign-in can use (Graph wants ThreatHunting.Read.All).
EndpointOption = Annotated[
    bool,
    typer.Option(
        "--endpoint",
        help="Through the Defender for Endpoint API instead of Graph: device tables only, "
        "but the Azure CLI's sign-in can use it.",
    ),
]

ShowQueryOption = Annotated[
    bool, typer.Option("--show-query", help="Print the KQL instead of running it.")
]

# A window of time, for commands about what happened when (see core.timewindow).
TodayOption = Annotated[bool, typer.Option("--today", help="Since midnight, local time.")]
YesterdayOption = Annotated[bool, typer.Option("--yesterday", help="The whole of yesterday.")]
SinceOption = Annotated[
    str | None, typer.Option("--since", help="The last span of time, e.g. 6h, 7d.")
]
FromOption = Annotated[
    str | None,
    typer.Option(
        "--from",
        help="From this day (YYYY-MM-DD, today or yesterday), whole, or this moment "
        "(YYYY-MM-DDTHH:MM, local time; end it with Z for UTC).",
    ),
]
ToOption = Annotated[
    str | None,
    typer.Option("--to", help="Up to and including this day (YYYY-MM-DD), or up to this moment."),
]


def time_window(
    today: bool,
    yesterday: bool,
    since: str | None,
    start: str | None,
    end: str | None,
    default: Callable[[datetime], Window],
) -> Window:
    """The window --today, --yesterday, --since or --from and --to name, else ``default``."""
    return choose_window(
        today=today,
        yesterday=yesterday,
        since=duration(since),
        start=start,
        end=end,
        default=default,
    )
