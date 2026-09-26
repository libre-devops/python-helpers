"""Checking a list of devices against what you expect of them: once (``check``), or
again and again until every one passes (``watch``).
"""

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
    SortOption,
    UniqueOption,
    WhereOption,
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
    CheckRun,
    DeviceChecker,
    DeviceReport,
    Expectations,
    watch,
)


def register(app: typer.Typer) -> None:
    """Add ``check`` and ``watch`` to ``app``."""
    app.command("check")(check)
    app.command("watch")(watch_devices)


_STATUS_COLOURS = {"met": "green", "unmet": "yellow", "error": "red"}

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

DeviceGroupOption = Annotated[
    list[str] | None,
    typer.Option(
        "--device-group",
        help="Expect the device in this Defender device group (its name). Repeatable.",
    ),
]

GroupOption = Annotated[
    list[str] | None,
    typer.Option(
        "--group", help="Expect membership of this Entra group: its object id or name. Repeatable."
    ),
]

IntuneOption = Annotated[bool, typer.Option("--intune", help="Expect it enrolled in Intune.")]

CompliantOption = Annotated[
    bool, typer.Option("--compliant", help="Expect Intune to report it compliant.")
]

WorkersOption = Annotated[
    int,
    typer.Option("--workers", min=1, max=32, help="Devices looked up at once."),
]


def check(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    where: WhereOption = None,
    entra: EntraOption = True,
    defender: DefenderOption = True,
    active: ActiveOption = False,
    tag: TagOption = None,
    device_group: DeviceGroupOption = None,
    group: GroupOption = None,
    intune: IntuneOption = False,
    compliant: CompliantOption = False,
    workers: WorkersOption = 8,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Check a list of devices once, fast, against what you expect of them.

    By default each device must be in Entra and onboarded to Defender. Exits 3 when any
    device misses any expectation.
    """
    wanted = names(devices, from_file, column, sheet, where)
    expectations = _expectations(
        entra, defender, active, tag, device_group, group, intune, compliant
    )
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    run = _checker(runtime, selected, expectations, workers).check(wanted, expectations)
    _render_run(run, expectations, output)
    render.note(_summary(run, expectations) + f" (profile {selected.name})")
    if not run.complete:
        raise typer.Exit(ATTENTION)


def watch_devices(
    ctx: typer.Context,
    devices: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    where: WhereOption = None,
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
    device_group: DeviceGroupOption = None,
    group: GroupOption = None,
    intune: IntuneOption = False,
    compliant: CompliantOption = False,
    workers: WorkersOption = 8,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Check devices repeatedly until every one meets every expectation, or a limit hits.

    Progress goes to stderr after each pass; the final state goes to stdout. Exits 0
    when complete, 3 when a limit stopped it first, and 130 on Ctrl-C.
    """
    wanted = names(devices, from_file, column, sheet, where)
    expectations = _expectations(
        entra, defender, active, tag, device_group, group, intune, compliant
    )
    limits, described = _watch_limits(interval, timeout, max_passes)
    runtime = get_runtime(ctx).microsoft
    checker = _checker(runtime, runtime.profile(profile), expectations, workers)
    render.note(f"watching {len(wanted)} device(s) {described}; Ctrl-C to stop")
    last: list[CheckRun] = []  # the latest pass, shown if Ctrl-C stops the watch

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
    render.note(
        f"{_WATCH_ENDS[outcome.reason]} after {outcome.passes} pass(es), "
        f"{format_duration(timedelta(seconds=outcome.elapsed))}"
    )
    if not outcome.complete:
        raise typer.Exit(ATTENTION)


# Why a watch stopped, by PollOutcome.reason.
_WATCH_ENDS = {
    "complete": "every device meets every expectation",
    "timeout": "timed out before every device was complete",
    "max-passes": "reached --max-passes before every device was complete",
}


def _watch_limits(
    interval: str, timeout: str | None, max_passes: int | None
) -> tuple[PollLimits, str]:
    """A watch's limits, and how to say them: ``every 5m, up to 2h, at most 3 pass(es)``."""
    every = duration(interval) or timedelta(minutes=5)
    limit = duration(timeout)
    limits = PollLimits(
        interval=every.total_seconds(),
        timeout=limit.total_seconds() if limit else None,
        max_passes=max_passes,
    )
    described = f"every {format_duration(every)}"
    if limit:
        described += f", up to {format_duration(limit)}"
    if max_passes:
        described += f", at most {max_passes} pass(es)"
    return limits, described


def _expectations(
    entra: bool,
    defender: bool,
    active: bool,
    tags: list[str] | None,
    device_groups: list[str] | None,
    groups: list[str] | None,
    intune: bool,
    compliant: bool,
) -> Expectations:
    return Expectations(
        in_entra=entra,
        onboarded=defender,
        active=active,
        tags=tuple(tags or ()),
        device_groups=tuple(device_groups or ()),
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
        # How many checks it meets, so --sort met:desc puts the complete ones first.
        met = sum(1 for outcome in report.outcomes if outcome.status == "met")
        shown = f"{met}/{len(report.outcomes)}"
        cells: list[render.Cell] = [report.name, (shown, "green" if report.complete else "yellow")]
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
        ["DEVICE", "MET", *(check.upper() for check in checks)],
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
