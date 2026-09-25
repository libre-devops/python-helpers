"""``devices av-signature``: each device's antivirus versions, from Advanced Hunting."""

from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    ColumnOption,
    EndpointOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    SheetOption,
    ShowQueryOption,
    SortOption,
    UniqueOption,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.microsoft.devices import (
    AvStatus,
    av_query,
    av_statuses,
    version_key,
)


def register(app: typer.Typer) -> None:
    """Add ``av-signature`` to ``app``."""
    app.command("av-signature")(av_signature)


def av_signature(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    at_least: Annotated[
        str | None,
        typer.Option(
            "--at-least", metavar="VERSION", help="Flag signatures older than this, e.g. 1.419.0.0."
        ),
    ] = None,
    endpoint: EndpointOption = False,
    show_query: ShowQueryOption = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The Defender Antivirus signature, engine and platform versions of devices.

    One built-in Advanced Hunting query for every device named, through Graph like
    'xdr hunt' (or --endpoint). UP TO DATE is Defender's own definitions check. Exits 3
    when a device is not found, is out of date, or is older than --at-least.
    """
    wanted = names(devices, from_file, column, sheet)
    if at_least:
        version_key(at_least)  # a bad version fails before the query runs
    query = av_query(wanted)
    if show_query:
        render.echo(query)
        return
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    result = runtime.xdr(selected).hunt(query) if endpoint else runtime.graph(selected).hunt(query)
    statuses = av_statuses(wanted, result)
    render.emit(
        output,
        [
            "DEVICE",
            "MACHINE",
            "OS",
            "SIGNATURE",
            "ENGINE",
            "PLATFORM",
            "MODE",
            "UP TO DATE",
            "REPORTED",
        ],
        [_av_row(status, at_least) for status in statuses],
        [_av_record(status, at_least) for status in statuses],
    )
    missing = sum(1 for status in statuses if not status.found)
    stale = sum(1 for status in statuses if status.found and status.up_to_date is False)
    behind = sum(
        1 for status in statuses if at_least and status.found and status.older_than(at_least)
    )
    parts = [f"{len(statuses) - missing} found"]
    parts += [f"{missing} not found"] if missing else []
    parts += [f"{stale} out of date"] if stale else []
    parts += [f"{behind} older than {at_least}"] if behind else []
    render.note(", ".join(parts) + f" (profile {selected.name})")
    if missing or stale or behind:
        raise typer.Exit(ATTENTION)


def _av_row(status: AvStatus, at_least: str | None) -> list[render.Cell]:
    if not status.found:
        return [status.query, ("not found", "red"), "", "", "", "", "", "", ""]
    signature: render.Cell = status.signature
    if at_least and status.older_than(at_least):
        signature = (status.signature or "unknown", "yellow")
    fresh: render.Cell = "-"  # the definitions check does not apply, or has not run
    if status.up_to_date is not None:
        fresh = ("yes", "green") if status.up_to_date else ("no", "yellow")
    return [
        status.query,
        status.device_name,
        status.os_platform,
        signature,
        status.engine,
        status.platform,
        status.mode,
        fresh,
        render.when(status.reported),
    ]


def _av_record(status: AvStatus, at_least: str | None) -> dict[str, Any]:
    return {
        "query": status.query,
        "found": status.found,
        "device_id": status.device_id or None,
        "device_name": status.device_name or None,
        "os_platform": status.os_platform or None,
        "signature_version": status.signature or None,
        "engine_version": status.engine or None,
        "platform_version": status.platform or None,
        "mode": status.mode or None,
        "up_to_date": status.up_to_date,
        "older_than_minimum": status.older_than(at_least) if at_least and status.found else None,
        "reported": status.reported.isoformat() if status.reported else None,
    }
