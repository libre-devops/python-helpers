"""Config commands: create the config file from the template, or print where it lives."""

import os
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import get_runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.config import CONFIG_HEADER, default_config_path
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.microsoft.config import CONFIG_TEMPLATE as MICROSOFT_TEMPLATE

# The file 'config init' writes: shared settings, then each vendor's section.
TEMPLATE = "\n".join([CONFIG_HEADER, MICROSOFT_TEMPLATE])

config_app = typer.Typer(help="Create or locate the config file.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    app.add_typer(config_app, name="config")


@config_app.command("init")
def init(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write a config template, with example Microsoft profiles to fill in."""
    path = get_runtime(ctx).config_path or default_config_path()
    render.banner()
    if path.exists() and not force:
        raise ConfigError(f"{path} already exists", hint="pass --force to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    render.echo(f"Wrote {path}")
    render.note(f"Next: replace the placeholder ids, then run {brand.command('profiles')}.")


@config_app.command("path")
def path(ctx: typer.Context) -> None:
    """Print the path of the config file in use."""
    render.echo(str(get_runtime(ctx).config_path or default_config_path()))
