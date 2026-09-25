"""Logic App commands: check, audit and compare workflow definitions; read and validate them.

The offline commands, in local.py (check, params, references, connections, order, diff,
defaults, rewrite), read files and never touch the network; they take files or folders,
and a folder means every .json and .json.tftpl in it. azure.py's export and validate go
to Azure, and only read: validate asks the provider for its verdict and creates nothing.
"""

import typer

from libre_devops_helpers.cli.commands.logicapp import azure, local

logicapp_app = typer.Typer(
    rich_markup_mode="markdown",
    name="logicapp",
    help="Consumption Logic Apps: check, audit, compare, export and validate workflows.",
    no_args_is_help=True,
)
local.register(logicapp_app)
azure.register(logicapp_app)


def register(app: typer.Typer) -> None:
    """Add the ``logicapp`` commands to ``app``."""
    app.add_typer(logicapp_app)
