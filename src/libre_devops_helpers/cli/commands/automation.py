"""Azure Automation commands: accounts, runbook jobs, and a job's logs and output.

An account is named by its name (found across the subscriptions in scope, narrowed by
-g) or by its resource id. A job is named by its id; without one, 'logs' and 'output'
take the newest job, of --runbook when given. Everything reads.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core.errors import InputError, NotFoundError
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.automation import (
    STREAMS,
    AutomationAccount,
    AutomationClient,
    Job,
    JobStream,
)
from libre_devops_helpers.microsoft.config import Profile

automation_app = typer.Typer(
    rich_markup_mode="markdown",
    name="automation",
    help="Azure Automation: accounts, runbook jobs, and each job's logs and output.",
    no_args_is_help=True,
)

_STATUS_COLOURS = {"Completed": "green", "Running": "cyan", "Failed": "red", "Suspended": "red"}
_STREAM_COLOURS = {"Error": "red", "Warning": "yellow", "Verbose": "bright_black"}

AccountArgument = Annotated[
    str, typer.Argument(metavar="ACCOUNT", help="The Automation account: its name or resource id.")
]
GroupOption = Annotated[
    str | None,
    typer.Option("--resource-group", "-g", help="The account's resource group, when names repeat."),
]
SubscriptionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--subscription",
        "-s",
        help="Subscription id to search. Repeatable. Default: the profile's subscription, "
        "else every one in the tenant.",
        show_default=False,
    ),
]
RunbookOption = Annotated[
    str | None, typer.Option("--runbook", "-r", help="Only this runbook's jobs.")
]
JobArgument = Annotated[
    str | None,
    typer.Argument(
        metavar="[JOB]",
        help="The job id. Default: the newest job (of --runbook).",
        show_default=False,
    ),
]


def register(app: typer.Typer) -> None:
    """Add the ``automation`` commands to ``app`` (the ``azure`` group)."""
    app.add_typer(automation_app)


def _scope(runtime: MicrosoftRuntime, profile: Profile, given: list[str] | None) -> list[str]:
    if given:
        return given
    if profile.subscription_id:
        return [profile.subscription_id]
    return runtime.subscription_ids(profile)


def _account(
    runtime: MicrosoftRuntime,
    profile: Profile,
    ref: str,
    group: str | None,
    subscriptions: list[str] | None,
) -> tuple[AutomationClient, AutomationAccount]:
    client = runtime.automation(profile)
    # A resource id needs no search, so the subscriptions are only listed for a name.
    scope = [] if ref.strip().startswith("/") else _scope(runtime, profile, subscriptions)
    return client, client.find_account(ref, scope, resource_group=group)


@automation_app.command("accounts")
def accounts(
    ctx: typer.Context,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the Automation accounts in the subscriptions in scope."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    found = runtime.automation(selected).accounts(_scope(runtime, selected, subscription))
    render.emit(
        output,
        ["ACCOUNT", "RESOURCE GROUP", "LOCATION", "SUBSCRIPTION"],
        [[item.name, item.resource_group, item.location, item.subscription_id] for item in found],
        [dict(item.raw) for item in found],
    )
    render.note(f"{len(found)} account(s)")


@automation_app.command("jobs")
def jobs(
    ctx: typer.Context,
    account: AccountArgument,
    runbook: RunbookOption = None,
    status: Annotated[
        list[str] | None,
        typer.Option(
            "--status",
            help="Only jobs in this state, e.g. failed, completed, running. Repeatable.",
        ),
    ] = None,
    failed: Annotated[
        bool, typer.Option("--failed", help="Only jobs that failed, were suspended or stopped.")
    ] = False,
    since: Annotated[
        str | None, typer.Option("--since", help="Only jobs created in this window, e.g. 24h, 7d.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 20,
    resource_group: GroupOption = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List a runbook's recent jobs (runs), newest first: when, how long, and how each ended.

    Jobs are kept for 30 days. Exits 3 when any job shown failed, was suspended or stopped.
    """
    runtime = get_runtime(ctx).microsoft
    client, found = _account(
        runtime, runtime.profile(profile), account, resource_group, subscription
    )
    window = duration(since)
    wanted = {item.casefold() for item in status or ()}
    now = datetime.now(UTC)
    shown = [
        job
        for job in client.jobs(found)
        if (runbook is None or job.runbook.casefold() == runbook.casefold())
        and (not wanted or job.status.casefold() in wanted)
        and (not failed or job.failed)
        and (window is None or (job.created is not None and now - job.created <= window))
    ][:limit]
    render.emit(
        output,
        ["JOB", "RUNBOOK", "STATUS", "STARTED", "TOOK", "RUN ON"],
        [_job_row(job, now) for job in shown],
        [dict(job.raw) for job in shown],
    )
    failures = sum(1 for job in shown if job.failed)
    note = f"{len(shown)} job(s) in {found.name}"
    if failures:
        note += f", {failures} failed"
    render.note(note)
    if failures:
        raise typer.Exit(ATTENTION)


@automation_app.command("logs")
def logs(
    ctx: typer.Context,
    account: AccountArgument,
    job: JobArgument = None,
    runbook: RunbookOption = None,
    stream: Annotated[
        list[str] | None,
        typer.Option(
            "--stream",
            help=f"Only these streams: {', '.join(STREAMS)}. Repeatable. Default: all.",
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Read each record in full, not its summary (a call each)."),
    ] = False,
    resource_group: GroupOption = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A job's logs, oldest first: its output, warnings, errors and other streams.

    Without a job id, the newest job, of --runbook when given. Verbose, progress and debug
    records appear only when the runbook turns them on. Exits 3 when the job failed.
    """
    kinds = _stream_kinds(stream)
    runtime = get_runtime(ctx).microsoft
    client, found = _account(
        runtime, runtime.profile(profile), account, resource_group, subscription
    )
    chosen = client.job(found, job or _newest(client, found, runbook).id)
    records = [
        item for item in client.streams(found, chosen.id) if kinds is None or item.stream in kinds
    ]
    if full:
        records = [client.stream(found, chosen.id, item.id) for item in records]
    if output is Output.TABLE:
        render.echo(render.pairs(_job_pairs(found, chosen)))
        render.echo()
    render.emit(
        output,
        ["TIME", "STREAM", "MESSAGE"],
        [
            [
                render.when(item.time),
                (item.stream, _STREAM_COLOURS.get(item.stream)),
                item.message,
            ]
            for item in records
        ],
        {
            "job": dict(chosen.raw),
            "streams": [_stream_record(item) for item in records],
        },
    )
    render.note(f"{len(records)} record(s)")
    if chosen.failed:
        raise typer.Exit(ATTENTION)


@automation_app.command("output")
def output_text(
    ctx: typer.Context,
    account: AccountArgument,
    job: JobArgument = None,
    runbook: RunbookOption = None,
    resource_group: GroupOption = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
) -> None:
    """A job's output as plain text, as the portal's Output tab shows it, for piping.

    Without a job id, the newest job, of --runbook when given.
    """
    runtime = get_runtime(ctx).microsoft
    client, found = _account(
        runtime, runtime.profile(profile), account, resource_group, subscription
    )
    chosen = job or _newest(client, found, runbook).id
    text = client.output(found, chosen)
    render.echo(text.rstrip("\n"))
    render.note(f"job {chosen} in {found.name}")


def _newest(client: AutomationClient, account: AutomationAccount, runbook: str | None) -> Job:
    for job in client.jobs(account):
        if runbook is None or job.runbook.casefold() == runbook.casefold():
            return job
    what = f"runbook {runbook!r}" if runbook else account.name
    raise NotFoundError(f"no jobs for {what} in the last 30 days")


def _stream_kinds(given: list[str] | None) -> set[str] | None:
    if not given:
        return None
    kinds = set()
    for item in given:
        kind = STREAMS.get(item.strip().casefold())
        if kind is None:
            raise InputError(f"unknown stream {item!r}", hint=f"use one of {', '.join(STREAMS)}")
        kinds.add(kind)
    return kinds


def _job_row(job: Job, now: datetime) -> list[render.Cell]:
    return [
        job.id,
        job.runbook,
        (job.status, "red" if job.failed else _STATUS_COLOURS.get(job.status)),
        render.when(job.started or job.created, now=now),
        _took(job, now),
        job.run_on or "Azure",
    ]


def _took(job: Job, now: datetime) -> str:
    if job.started is None:
        return "-"
    end = job.ended or now
    suffix = "" if job.ended else " so far"
    return format_duration(end - job.started) + suffix


def _job_pairs(account: AutomationAccount, job: Job) -> list[tuple[str, str]]:
    now = datetime.now(UTC)
    pairs = [
        ("Account", f"{account.name} ({account.resource_group})"),
        ("Runbook", job.runbook),
        ("Job", job.id),
        ("Status", job.status),
        ("Started", render.when(job.started or job.created)),
        ("Took", _took(job, now)),
        ("Run on", job.run_on or "Azure"),
    ]
    if job.started_by:
        pairs.append(("Started by", job.started_by))
    if job.exception:
        pairs.append(("Exception", job.exception))
    return pairs


def _stream_record(item: JobStream) -> dict[str, Any]:
    return {
        "id": item.id,
        "time": item.time.isoformat() if item.time else None,
        "stream": item.stream,
        "message": item.message,
    }
