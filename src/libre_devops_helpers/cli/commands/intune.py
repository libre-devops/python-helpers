"""Intune commands: look managed devices up by name."""

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    ColumnOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output

intune_app = typer.Typer(help="Intune: managed devices and compliance.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    app.add_typer(intune_app, name="intune")


@intune_app.command("devices")
def devices(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Look devices up in Intune: compliance, last sync, owner and Entra link.

    Needs DeviceManagementManagedDevices.Read.All, which the Azure CLI's token does not
    carry: use a profile with its own app registration. Exits 3 when any device is not
    enrolled.
    """
    wanted = names(devices, from_file, column)
    runtime = get_runtime(ctx).microsoft
    intune = runtime.intune(runtime.profile(profile))
    results = [(name, intune.find_devices(name)) for name in wanted]
    rows: list[list[render.Cell]] = []
    for name, found in results:
        if not found:
            rows.append([name, ("not enrolled", "red"), "", "", "", "", ""])
            continue
        for index, device in enumerate(found):
            rows.append(
                [
                    name if index == 0 else ("  older record", "bright_black"),
                    (device.compliance_state, "green" if device.compliant else "yellow"),
                    f"{device.operating_system} {device.os_version}".strip(),
                    render.when(device.last_sync),
                    device.user_principal_name,
                    device.azure_ad_device_id,
                    device.serial_number,
                ]
            )
    render.emit(
        output,
        ["DEVICE", "COMPLIANCE", "OS", "LAST SYNC", "USER", "ENTRA DEVICE ID", "SERIAL"],
        rows,
        [
            {"query": name, "devices": [dict(device.raw) for device in found]}
            for name, found in results
        ],
    )
    missing = [name for name, found in results if not found]
    render.note(f"{len(results) - len(missing)} of {len(results)} enrolled in Intune")
    if missing:
        raise typer.Exit(ATTENTION)
