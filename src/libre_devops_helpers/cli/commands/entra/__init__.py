"""Entra commands: devices, groups, users and their roles and sign-ins, and tenant-wide reads.

Each part adds its own commands to ``entra_app``: devices.py (``devices``,
``device-groups``), groups.py (``group-devices``, ``group-members``), users.py
(``user-groups``, ``user-roles``, ``sign-ins``) and tenant.py (``app-credentials``,
``ca-policies``). The token commands join them from token.py.
"""

import typer

from libre_devops_helpers.cli.commands.entra import devices, groups, tenant, users

entra_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Entra ID: devices, users, groups, roles and apps.",
    no_args_is_help=True,
)
# In the order --help lists them.
devices.register(entra_app)
groups.register(entra_app)
users.register(entra_app)
tenant.register(entra_app)


def register(app: typer.Typer) -> None:
    """Add the ``entra`` commands to ``app``."""
    app.add_typer(entra_app, name="entra")
