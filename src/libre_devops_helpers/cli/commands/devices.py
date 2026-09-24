"""Device commands across Entra, Defender and Intune: check, watch, show, and AV versions."""

from datetime import timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION, INTERRUPTED
from libre_devops_helpers.cli.options import (
    ColumnOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    SheetOption,
    duration,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core.poll import PollLimits
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.devices import (
    AvStatus,
    CheckRun,
    DeviceChecker,
    DeviceReport,
    Expectations,
    av_query,
    av_statuses,
    inspect_device,
    version_key,
    watch,
)

devices_app = typer.Typer(
    help="Devices across Entra, Defender and Intune: check, watch, show, and AV versions.",
    no_args_is_help=True,
)

_STATUS_COLOURS = {"met": "green", "unmet": "yellow", "error": "red"}
_FINDING_COLOURS = {"ok": "green", "info": None, "warn": "yellow"}

EntraOption = Annotated[
    bool, typer.Option("--entra/--no-entra", help="Expect the device in Entra ID.")
]
DefenderOption = Annotated[
    bool, typer.Option("--defender/--no-defender", help="Expect it onboarded to Defender.")
]
ActiveOption = Annotated[
    bool, typer.Option("--active", help="Expect Defender health to be Active.")
]
TagOption = Annotated[
    list[str] | None,
    typer.Option("--tag", help="Expect this Defender machine tag. Repeatable."),
]
GroupOption = Annotated[
    list[str] | None,
    typer.Option("--group", help="Expect membership of this Entra group (name or id). Repeatable."),
]
IntuneOption = Annotated[bool, typer.Option("--intune", help="Expect it enrolled in Intune.")]
CompliantOption = Annotated[
    bool, typer.Option("--compliant", help="Expect Intune to report it compliant.")
]
WorkersOption = Annotated[
    int,
    typer.Option("--workers", min=1, max=32, help="Devices looked up at once."),
]


def register(app: typer.Typer) -> None:
    app.add_typer(devices_app, name="devices")
    app.add_typer(devices_app, name="device", hidden=True)  # the singular works as well


def _expectations(
    entra: bool,
    defender: bool,
    active: bool,
    tags: list[str] | None,
    groups: list[str] | None,
    intune: bool,
    compliant: bool,
) -> Expectations:
    return Expectations(
        in_entra=entra,
        onboarded=defender,
        active=active,
        tags=tuple(tags or ()),
        groups=tuple(groups or ()),
        in_intune=intune,
        compliant=compliant,
    )


def _checker(
    runtime: MicrosoftRuntime, profile: Profile, expectations: Expectations, workers: int
) -> DeviceChecker:
    # Only build the clients the expectations need, so an Entra-only check never asks
    # Defender or Intune for a token.
    return DeviceChecker(
        entra=runtime.entra(profile) if expectations.needs_entra else None,
        xdr=runtime.xdr(profile) if expectations.needs_defender else None,
        intune=runtime.intune(profile) if expectations.needs_intune else None,
        workers=workers,
    )


def _render_run(run: CheckRun, expectations: Expectations, output: Output) -> None:
    checks = expectations.checks
    rows: list[list[render.Cell]] = []
    for report in run.reports:
        cells: list[render.Cell] = [report.name]
        for check in checks:
            outcome = report.outcome(check)
            if outcome is None:
                cells.append("")
            elif outcome.status == "met":
                cells.append(("ok", "green"))
            else:
                cells.append((outcome.detail, _STATUS_COLOURS[outcome.status]))
        rows.append(cells)
    render.emit(
        output,
        ["DEVICE", *(check.upper() for check in checks)],
        rows,
        {
            "complete": run.complete,
            "checked_at": run.checked_at,
            "error": run.error,
            "devices": [_record(report) for report in run.reports],
        },
    )


def _record(report: DeviceReport) -> dict[str, Any]:
    return {
        "name": report.name,
        "complete": report.complete,
        "checks": {
            outcome.check: {"status": outcome.status, "detail": outcome.detail}
            for outcome in report.outcomes
        },
        "entra": [dict(device.raw) for device in report.entra],
        "defender": [dict(record.raw) for record in report.defender.records]
        if report.defender
        else [],
        "intune": [dict(device.raw) for device in report.intune],
    }


def _summary(run: CheckRun, expectations: Expectations) -> str:
    counts = run.counts(expectations.checks)
    done = sum(1 for report in run.reports if report.complete)
    parts = ", ".join(f"{check} {count}/{run.expected}" for check, count in counts.items())
    return f"{done}/{run.expected} complete ({parts})"


@devices_app.command("check")
def check(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    entra: EntraOption = True,
    defender: DefenderOption = True,
    active: ActiveOption = False,
    tag: TagOption = None,
    group: GroupOption = None,
    intune: IntuneOption = False,
    compliant: CompliantOption = False,
    workers: WorkersOption = 8,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Check a list of devices once, fast, against what you expect of them.

    By default each device must be in Entra and onboarded to Defender. Exits 3 when any
    device misses any expectation.
    """
    wanted = names(devices, from_file, column, sheet)
    expectations = _expectations(entra, defender, active, tag, group, intune, compliant)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    run = _checker(runtime, selected, expectations, workers).check(wanted, expectations)
    _render_run(run, expectations, output)
    render.note(_summary(run, expectations) + f" (profile {selected.name})")
    if not run.complete:
        raise typer.Exit(ATTENTION)


@devices_app.command("watch")
def watch_devices(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    interval: Annotated[
        str, typer.Option("--interval", help="Time between passes, e.g. 90s, 5m, 1h.")
    ] = "5m",
    timeout: Annotated[
        str | None,
        typer.Option("--timeout", help="Give up after this long, e.g. 2h. Default: never."),
    ] = None,
    max_passes: Annotated[
        int | None,
        typer.Option("--max-passes", min=1, help="Give up after this many passes."),
    ] = None,
    recheck: Annotated[
        bool,
        typer.Option("--recheck", help="Recheck devices that already met everything, each pass."),
    ] = False,
    entra: EntraOption = True,
    defender: DefenderOption = True,
    active: ActiveOption = False,
    tag: TagOption = None,
    group: GroupOption = None,
    intune: IntuneOption = False,
    compliant: CompliantOption = False,
    workers: WorkersOption = 8,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Check devices repeatedly until every one meets every expectation, or a limit hits.

    Progress goes to stderr after each pass; the final state goes to stdout. Exits 0
    when complete, 3 when a limit stopped it first, and 130 on Ctrl-C.
    """
    wanted = names(devices, from_file, column, sheet)
    expectations = _expectations(entra, defender, active, tag, group, intune, compliant)
    every = duration(interval) or timedelta(minutes=5)
    limit = duration(timeout)
    limits = PollLimits(
        interval=every.total_seconds(),
        timeout=limit.total_seconds() if limit else None,
        max_passes=max_passes,
    )
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    checker = _checker(runtime, selected, expectations, workers)
    stop = f", up to {format_duration(limit)}" if limit else ""
    stop += f", at most {max_passes} pass(es)" if max_passes else ""
    render.note(
        f"watching {len(wanted)} device(s) every {format_duration(every)}{stop}; Ctrl-C to stop"
    )
    last: list[CheckRun] = []

    def on_pass(number: int, run: CheckRun) -> None:
        last[:] = [run]
        prefix = f"pass {number}: "
        if run.error:
            render.warn(prefix + f"failed, will retry: {run.error}")
        else:
            render.note(prefix + _summary(run, expectations))

    def on_wait(seconds: float) -> None:
        render.note(f"next pass in {format_duration(timedelta(seconds=seconds))}")

    try:
        outcome = watch(
            checker,
            wanted,
            expectations,
            limits,
            recheck=recheck,
            clock=runtime.runtime.clock,
            sleep=runtime.runtime.sleep,
            on_pass=on_pass,
            on_wait=on_wait,
        )
    except KeyboardInterrupt:
        if last:
            _render_run(last[0], expectations, output)
        render.note("stopped")
        raise typer.Exit(INTERRUPTED) from None

    _render_run(outcome.result, expectations, output)
    reasons = {
        "complete": "every device meets every expectation",
        "timeout": "timed out before every device was complete",
        "max-passes": "reached --max-passes before every device was complete",
    }
    render.note(
        f"{reasons[outcome.reason]} after {outcome.passes} pass(es), "
        f"{format_duration(timedelta(seconds=outcome.elapsed))}"
    )
    if not outcome.complete:
        raise typer.Exit(ATTENTION)


@devices_app.command("show")
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
    warned = any(finding.level == "warn" for finding in view.findings)
    if output is not Output.TABLE:
        render.emit(
            output,
            ["LEVEL", "FINDING"],
            [[finding.level, finding.message] for finding in view.findings],
            {
                "name": view.name,
                "findings": [
                    {"level": finding.level, "message": finding.message}
                    for finding in view.findings
                ],
                "entra": [
                    {
                        "device": dict(item.raw),
                        "groups": [dict(group.raw) for group in view.groups.get(item.id, ())],
                    }
                    for item in view.entra
                ],
                "defender": [dict(record.raw) for record in view.defender.records]
                if view.defender
                else None,
                "intune": None if view.intune is None else [dict(item.raw) for item in view.intune],
            },
        )
        if warned:
            raise typer.Exit(ATTENTION)
        return

    render.echo(render.title(f"Entra ({len(view.entra)} object(s))"))
    for item in view.entra:
        groups = ", ".join(group.display_name for group in view.groups.get(item.id, ())) or "-"
        render.echo(
            render.pairs(
                [
                    ("Name", item.display_name),
                    ("Object id", item.id),
                    ("Device id", item.device_id),
                    ("OS", f"{item.operating_system} {item.os_version}".strip()),
                    ("Enabled", render.yes_no(item.enabled)),
                    ("Trust", item.trust_type),
                    ("Last sign-in", render.when(item.last_sign_in)),
                    ("Groups", groups),
                ]
            )
        )
        render.echo()
    if view.defender is not None:
        machine = view.defender.machine
        render.echo(render.title(f"Defender ({len(view.defender.records)} record(s))"))
        if machine is not None:
            render.echo(
                render.pairs(
                    [
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
                )
            )
        render.echo()
    if view.intune is not None:
        render.echo(render.title(f"Intune ({len(view.intune)} record(s))"))
        for managed in view.intune[:1]:
            render.echo(
                render.pairs(
                    [
                        ("Name", managed.device_name),
                        ("Compliance", managed.compliance_state),
                        ("Last sync", render.when(managed.last_sync)),
                        ("User", managed.user_principal_name),
                        ("Entra device id", managed.azure_ad_device_id),
                    ]
                )
            )
        render.echo()
    render.echo(render.title("Findings"))
    render.echo(
        render.table(
            ["LEVEL", "FINDING"],
            [
                [(finding.level, _FINDING_COLOURS[finding.level]), finding.message]
                for finding in view.findings
            ],
        )
    )
    if warned:
        raise typer.Exit(ATTENTION)


@devices_app.command("av-signature")
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
    endpoint: Annotated[
        bool,
        typer.Option(
            "--endpoint",
            help="Through the Defender for Endpoint API, as 'xdr hunt --endpoint' does.",
        ),
    ] = False,
    show_query: Annotated[
        bool, typer.Option("--show-query", help="Print the KQL instead of running it.")
    ] = False,
    profile: ProfileOption = None,
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
    fresh = {True: ("yes", "green"), False: ("no", "yellow")}.get(status.up_to_date, "-")
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
