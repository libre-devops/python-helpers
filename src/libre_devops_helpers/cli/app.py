"""The ldo root command.

Commands parse arguments and render results; the work happens in the importable
subpackages. Library errors are turned into a message and an exit code here,
and only here.
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from libre_devops_helpers import __version__
from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands import (
    az,
    azure,
    config,
    devices,
    entra,
    graph,
    incidents,
    intune,
    keyvault,
    logicapp,
    logs,
    pim,
    profiles,
    snow,
    token,
    welcome,
    xdr,
)
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.log import LOG_FORMATS, configure_logging

app = typer.Typer(
    name=brand.COMMAND,
    help=f"{brand.DISPLAY_NAME}: fast, read-only helpers for Azure, Entra ID, Defender, "
    "Intune, Key Vault and Log Analytics.",
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"{brand.COMMAND} {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help=f"Config file. Default: ${brand.CONFIG_ENV}, "
            f"else ~/.config/{brand.CONFIG_DIR}/config.toml.",
            dir_okay=False,
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[
        int, typer.Option("--verbose", "-v", count=True, help="-v info, -vv debug (stderr).")
    ] = 0,
    log_format: Annotated[
        str,
        typer.Option(
            "--log-format",
            envvar=brand.LOG_FORMAT_ENV,
            help=f"Log line format on stderr: {', '.join(LOG_FORMATS)} (OTLP/JSON).",
        ),
    ] = "text",
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            envvar=brand.LOG_LEVEL_ENV,
            help="Minimum log level (trace, debug, info, warn, error, fatal). -v and -vv win.",
            show_default=False,
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    configure_logging(verbose, log_format, log_level)
    # Tests pass a prepared Runtime as obj; a real run builds one here.
    if not isinstance(ctx.obj, Runtime):
        ctx.obj = Runtime(config_path=config_path)
    elif config_path is not None:
        ctx.obj.config_path = config_path
    ctx.call_on_close(ctx.obj.close)
    if ctx.invoked_subcommand is None:
        # Bare 'ldo': a greeting, then the help.
        render.banner()
        typer.echo(ctx.get_help())
        raise typer.Exit()


for _module in (
    welcome,
    config,
    profiles,
    az,
    entra,
    graph,
    xdr,
    intune,
    azure,
    keyvault,
    logs,
    logicapp,
    pim,
    devices,
    snow,
):
    _module.register(app)
# Token commands are about Entra-issued tokens, so they live in the entra group.
token.register(entra.entra_app)
# Incidents are Defender XDR's (Sentinel's included), so they live in the xdr group.
incidents.register(xdr.xdr_app)


def main() -> None:
    """Console entry point: run the app and report library errors cleanly."""
    try:
        app()
    except LdoError as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        if exc.hint:
            typer.secho(f"hint: {exc.hint}", fg="yellow", err=True)
        sys.exit(exc.exit_code)
