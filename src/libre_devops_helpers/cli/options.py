"""Options shared by several commands, and access to the per-invocation Runtime."""

import sys
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import InputError, LdoError
from libre_devops_helpers.core.inputs import read_names
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
        "--output", "-o", help="table for people, json for scripts, csv for spreadsheets."
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
