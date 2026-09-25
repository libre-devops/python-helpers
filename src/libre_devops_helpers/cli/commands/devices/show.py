"""``devices show``: one device across Entra, Defender and Intune, and what looks wrong."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.microsoft.devices import (
    DeviceView,
    inspect_device,
)
from libre_devops_helpers.microsoft.entra import EntraDevice, EntraGroup
from libre_devops_helpers.microsoft.intune import ManagedDevice
from libre_devops_helpers.microsoft.xdr import Machine


def register(app: typer.Typer) -> None:
    """Add ``show`` to ``app``."""
    app.command("show")(show)


_FINDING_COLOURS = {"ok": "green", "info": None, "warn": "yellow"}


def show(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name: FQDN or short hostname.")],
    intune: Annotated[
        bool, typer.Option("--intune", help="Also read Intune (needs a token that can).")
    ] = False,
    defender: Annotated[
        bool, typer.Option("--defender/--no-defender", help="Read Defender.")
    ] = True,
    stale_after: Annotated[
        str, typer.Option("--stale-after", help="Warn when Defender last saw it longer ago.")
    ] = "7d",
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Show one device across Entra, Defender and Intune, and what looks wrong about it.

    Exits 3 when there is any warning.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    view = inspect_device(
        device,
        entra=runtime.entra(selected),
        xdr=runtime.xdr(selected) if defender else None,
        intune=runtime.intune(selected) if intune else None,
        stale_after=duration(stale_after) or timedelta(days=7),
    )
    if output is Output.TABLE:
        _print_view(view)
    else:
        findings = [[finding.level, finding.message] for finding in view.findings]
        render.emit(output, ["LEVEL", "FINDING"], findings, _view_record(view))
    if any(finding.level == "warn" for finding in view.findings):
        raise typer.Exit(ATTENTION)


def _view_record(view: DeviceView) -> dict[str, Any]:
    """Everything ``devices show`` found, as the services returned it, for -o json."""
    return {
        "name": view.name,
        "findings": [
            {"level": finding.level, "message": finding.message} for finding in view.findings
        ],
        "entra": [
            {
                "device": dict(item.raw),
                "groups": [dict(group.raw) for group in view.groups.get(item.id, ())],
            }
            for item in view.entra
        ],
        "defender": None
        if view.defender is None
        else [dict(record.raw) for record in view.defender.records],
        "intune": None if view.intune is None else [dict(item.raw) for item in view.intune],
    }


def _print_view(view: DeviceView) -> None:
    """A section for each service, then the findings."""
    render.echo(render.title(f"Entra ({len(view.entra)} object(s))"))
    for item in view.entra:
        render.echo(render.pairs(_entra_pairs(item, view.groups.get(item.id, ()))))
        render.echo()
    if view.defender is not None:
        render.echo(render.title(f"Defender ({len(view.defender.records)} record(s))"))
        if view.defender.machine is not None:
            render.echo(render.pairs(_defender_pairs(view.defender.machine)))
        render.echo()
    if view.intune is not None:
        render.echo(render.title(f"Intune ({len(view.intune)} record(s))"))
        if view.intune:
            render.echo(render.pairs(_intune_pairs(view.intune[0])))  # the newest
        render.echo()
    render.echo(render.title("Findings"))
    rows: list[list[render.Cell]] = [
        [(finding.level, _FINDING_COLOURS[finding.level]), finding.message]
        for finding in view.findings
    ]
    render.echo(render.table(["LEVEL", "FINDING"], rows))


def _entra_pairs(item: EntraDevice, groups: Sequence[EntraGroup]) -> list[tuple[str, str]]:
    return [
        ("Name", item.display_name),
        ("Object id", item.id),
        ("Device id", item.device_id),
        ("OS", f"{item.operating_system} {item.os_version}".strip()),
        ("Enabled", render.yes_no(item.enabled)),
        ("Trust", item.trust_type),
        ("Last sign-in", render.when(item.last_sign_in)),
        ("Groups", ", ".join(group.display_name for group in groups) or "-"),
    ]


def _defender_pairs(machine: Machine) -> list[tuple[str, str]]:
    return [
        ("Name", machine.computer_dns_name),
        ("Machine id", machine.id),
        ("Onboarding", machine.onboarding_status),
        ("Health", machine.health_status),
        ("Last seen", render.when(machine.last_seen)),
        ("OS", f"{machine.os_platform} {machine.os_version}".strip()),
        ("Agent", machine.agent_version),
        ("Risk", machine.risk_score),
        ("Exposure", machine.exposure_level),
        ("Tags", ", ".join(machine.machine_tags)),
        ("Entra device id", machine.aad_device_id),
    ]


def _intune_pairs(managed: ManagedDevice) -> list[tuple[str, str]]:
    return [
        ("Name", managed.device_name),
        ("Compliance", managed.compliance_state),
        ("Last sync", render.when(managed.last_sync)),
        ("User", managed.user_principal_name),
        ("Entra device id", managed.azure_ad_device_id),
    ]
