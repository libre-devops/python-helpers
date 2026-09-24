"""The welcome command: the banner, where the config lives, and what to run next."""

import typer

from libre_devops_helpers import __version__
from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import get_runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.config import default_config_path


def register(app: typer.Typer) -> None:
    app.command("welcome")(welcome)


def welcome(ctx: typer.Context) -> None:
    """Say hello: the banner, the version, the config file, and the next step."""
    render.banner(force=True)
    runtime = get_runtime(ctx)
    path = runtime.config_path or default_config_path()
    file = runtime.optional_config_file()
    render.echo(
        render.pairs(
            [
                ("Version", f"{brand.COMMAND} {__version__}"),
                ("Config", f"{path}" + ("" if file else " (not created yet)")),
            ]
        )
    )
    render.echo()
    if file is None:
        steps = [
            (brand.command("config init"), "write a config file to fill in"),
            (brand.command("--help"), "see every command"),
        ]
    else:
        steps = [
            (brand.command("profiles"), "check your profiles and sign-ins"),
            (brand.command("devices check --help"), "check devices across Entra and Defender"),
            (brand.command("--help"), "see every command"),
        ]
    render.echo(render.title("Next"))
    render.echo(render.pairs((command.strip("'"), purpose) for command, purpose in steps))
