"""Device commands across Entra, Defender and Intune: check, watch, show, and AV versions.

``check`` and ``watch`` are in checks.py, ``show`` in show.py and ``av-signature`` in
antivirus.py; each adds its own commands to ``devices_app``.
"""

import typer

from libre_devops_helpers.cli.commands.devices import antivirus, checks, show

devices_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Devices across Entra, Defender and Intune: check, watch, show, and AV versions.",
    no_args_is_help=True,
)
checks.register(devices_app)
show.register(devices_app)
antivirus.register(devices_app)


def register(app: typer.Typer) -> None:
    """Add the ``devices`` commands to ``app``, where ``device`` finds them too."""
    app.add_typer(devices_app, name="devices")
    app.add_typer(devices_app, name="device", hidden=True)  # the singular works as well
