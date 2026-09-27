"""Defender XDR commands: machines, alerts, vulnerabilities, indicators and hunting.

Each part adds its own commands to ``xdr_app``: machines.py (``machines``, ``stale``),
findings.py (``alerts``, ``vulns``, ``indicators``), hunting.py (``hunt``,
``timeline``), detections.py (``detections list``, ``show`` and ``export``) and
analyzer.py (``analyzer``, for MDE Client Analyzer results). The incident commands join
them from incidents.py.
"""

import typer

from libre_devops_helpers.cli.commands.xdr import analyzer, detections, findings, hunting, machines

xdr_app = typer.Typer(
    rich_markup_mode="markdown",
    help=(
        "Defender XDR: incidents (Sentinel's included), and Defender for Endpoint "
        "machines, alerts, vulnerabilities and hunting."
    ),
    no_args_is_help=True,
)
machines.register(xdr_app)
findings.register(xdr_app)
hunting.register(xdr_app)
detections.register(xdr_app)
analyzer.register(xdr_app)


def register(app: typer.Typer) -> None:
    """Add the ``xdr`` commands to ``app``."""
    app.add_typer(xdr_app, name="xdr")
