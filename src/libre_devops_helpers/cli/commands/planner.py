"""``planner``: Microsoft Planner plans and tasks, and raising a task for each Message Center
post a plan does not have one for yet, or one a month summing them up."""

from datetime import UTC, datetime
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands.news import (
    CategoryOption,
    DateOption,
    MajorOption,
    SecurityOption,
    ServiceOption,
    SinceOption,
    services,
    window,
)
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.microsoft.news import (
    MESSAGE_KEY,
    ROLLUP_TITLE,
    Layout,
    Message,
    Rollup,
    listed,
    months,
    task_notes,
    task_title,
)
from libre_devops_helpers.microsoft.planner import (
    TITLE_LIMIT,
    Bucket,
    Plan,
    PlannerClient,
    Task,
    keyed,
)

# What a rollup still needs, as a table shows it: the rest are shown green.
_ROLLUP_TO_DO = frozenset({"to raise", "to update"})

planner_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Microsoft Planner: plans, buckets and tasks, and tasks for Message Center posts.",
    no_args_is_help=True,
)

PlanArgument = Annotated[str, typer.Argument(metavar="PLAN", help="The plan, by title or id.")]


def register(app: typer.Typer) -> None:
    """Add the ``planner`` commands to ``app``."""
    app.add_typer(planner_app, name="planner")


@planner_app.command("plans")
def plans(
    ctx: typer.Context,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Your plans: those shared with you."""
    runtime = get_runtime(ctx).microsoft
    found = runtime.planner(runtime.profile(profile)).plans()
    render.emit(
        output,
        ["TITLE", "CREATED", "ID"],
        [[plan.title, render.moment(plan.created), plan.id] for plan in found],
        [
            {
                "id": plan.id,
                "title": plan.title,
                "owner": plan.owner or None,
                "created": plan.created.isoformat() if plan.created else None,
            }
            for plan in found
        ],
    )


@planner_app.command("buckets")
def buckets(
    ctx: typer.Context,
    plan: PlanArgument,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A plan's buckets: the columns of its board."""
    runtime = get_runtime(ctx).microsoft
    planner = runtime.planner(runtime.profile(profile))
    found = planner.buckets(planner.plan(plan).id)
    render.emit(
        output,
        ["BUCKET", "ID"],
        [[bucket.name, bucket.id] for bucket in found],
        [{"id": bucket.id, "name": bucket.name} for bucket in found],
    )


@planner_app.command("tasks")
def tasks(
    ctx: typer.Context,
    plan: PlanArgument,
    bucket: Annotated[
        str | None, typer.Option("--bucket", help="Only this bucket's tasks.")
    ] = None,
    open_only: Annotated[bool, typer.Option("--open", help="Only tasks not complete.")] = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A plan's tasks: each one's bucket, progress and dates."""
    runtime = get_runtime(ctx).microsoft
    planner = runtime.planner(runtime.profile(profile))
    chosen = planner.plan(plan)
    names = {item.id: item.name for item in planner.buckets(chosen.id)}
    found = planner.tasks(chosen.id)
    if bucket:
        wanted = planner.bucket(chosen.id, bucket).id
        found = [task for task in found if task.bucket_id == wanted]
    if open_only:
        found = [task for task in found if not task.done]
    render.emit(
        output,
        ["TITLE", "BUCKET", "DONE", "DUE", "CREATED", "ID"],
        [_task_row(task, names) for task in found],
        [_task_record(task, names) for task in found],
    )
    render.note(f"{len(found)} task(s) in {chosen.title}")


@planner_app.command("add-news")
def add_news(
    ctx: typer.Context,
    plan: PlanArgument,
    bucket: Annotated[str, typer.Option("--bucket", help="The bucket new tasks go in.")],
    date: DateOption = None,
    since: SinceOption = None,
    service: ServiceOption = None,
    security: SecurityOption = False,
    category: CategoryOption = None,
    major: MajorOption = False,
    layout: Annotated[
        Layout,
        typer.Option(
            "--layout",
            case_sensitive=False,
            help="How a task reads. sync: as Microsoft's own Message Center sync to Planner "
            "writes them, the services, the title and the post's id in brackets, and the "
            "notes starting with its id, date, category and tags. short: the id, then the title.",
        ),
    ] = Layout.SYNC,
    write: Annotated[
        bool, typer.Option("--write", help="Raise the tasks, rather than only say which.")
    ] = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A task for each Message Center post the plan has none for yet, in one bucket: the
    posts changed in the last 7 days by default.

    A post has a task when any task in the plan (in any bucket, done or not) has a title
    holding its id in square brackets, as Microsoft's own Message Center sync writes them
    and as these are raised, or starting with it (MC1183010: and its title, the short
    layout). Without --write
    this only says which it would raise. Needs ServiceMessage.Read.All and a Planner scope
    (Tasks.ReadWrite to raise): use a profile with your own app registration. Exits 3
    when there are posts it has not raised a task for.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    planner = runtime.planner(selected)
    chosen = planner.plan(plan)
    column = planner.bucket(chosen.id, bucket)
    start, end, said = window(date, since, "7d")
    found = runtime.news(selected).messages(
        since=start,
        until=end,
        services=services(service, security),
        category=category,
        major=major,
    )
    raised = keyed(planner.tasks(chosen.id), MESSAGE_KEY)
    outcomes = [
        _raise(planner, chosen, column, item, raised, layout=layout, write=write) for item in found
    ]
    render.emit(
        output,
        ["MESSAGE", "UPDATED", "TITLE", "TASK"],
        [
            [item.id, render.when(item.updated), item.title, cell]
            for item, (cell, _) in zip(found, outcomes, strict=True)
        ],
        [
            {"message": item.id, "title": item.title, "task": state}
            for item, (_, state) in zip(found, outcomes, strict=True)
        ],
    )
    _summarise([state for _, state in outcomes], chosen, column, said, write=write)
    if any(state == "to raise" for _, state in outcomes):
        raise typer.Exit(ATTENTION)


@planner_app.command("add-rollup")
def add_rollup(
    ctx: typer.Context,
    plan: PlanArgument,
    bucket: Annotated[str, typer.Option("--bucket", help="The bucket new rollups go in.")],
    date: DateOption = None,
    since: SinceOption = None,
    service: ServiceOption = None,
    security: SecurityOption = False,
    category: CategoryOption = None,
    major: MajorOption = False,
    write: Annotated[
        bool,
        typer.Option("--write", help="Raise and update the rollups, rather than only say which."),
    ] = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """A task for each month's Message Center posts, summing them all up, in one bucket: the
    months the last 7 days fall in by default.

    A month's rollup lists every post last changed in that month (the whole month, not only
    the days asked for) and counts them by severity, service and category. Its title is
    Message Center rollup: 2026-09 and how many posts. A month the plan has a rollup for
    already (in any bucket, done or not) has it brought up to date instead, its progress
    left as it is. Without --write this only says what it would do. Needs what add-news
    does. Exits 3 when a rollup is to raise or to update.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    planner = runtime.planner(selected)
    chosen = planner.plan(plan)
    column = planner.bucket(chosen.id, bucket)
    start, end, _ = window(date, since, "7d")
    if start is None:
        raise typer.BadParameter(
            "give the first day, as in --date 2026-06-01..", param_hint="--date"
        )
    news = runtime.news(selected)
    wanted = services(service, security)
    rollups = []
    for month, first, after in months(start, end or datetime.now(UTC)):
        found = news.messages(
            since=first, until=after, services=wanted, category=category, major=major
        )
        if found:
            rollups.append(Rollup(month, tuple(found)))
    existing = keyed(planner.tasks(chosen.id), ROLLUP_TITLE)
    outcomes = [
        _roll(planner, chosen, column, rollup, existing.get(rollup.month), write=write)
        for rollup in rollups
    ]
    render.emit(
        output,
        ["MONTH", "POSTS", "NEW", "TASK"],
        [
            [rollup.month, str(len(rollup.messages)), str(new), _rollup_cell(state)]
            for rollup, (state, new) in zip(rollups, outcomes, strict=True)
        ],
        [
            {"month": rollup.month, "posts": len(rollup.messages), "new": new, "task": state}
            for rollup, (state, new) in zip(rollups, outcomes, strict=True)
        ],
    )
    states = [state for state, _ in outcomes]
    render.note(_rollup_summary(states, f"{chosen.title} / {column.name}", write=write))
    if _ROLLUP_TO_DO.intersection(states):
        raise typer.Exit(ATTENTION)


def _roll(
    planner: PlannerClient,
    plan: Plan,
    bucket: Bucket,
    rollup: Rollup,
    task: Task | None,
    *,
    write: bool,
) -> tuple[str, int]:
    """What happened to one month's rollup, and how many of its posts it did not list."""
    if task is None:
        if write:
            planner.create_task(plan.id, bucket.id, rollup.title, description=rollup.description)
        return ("raised" if write else "to raise"), len(rollup.messages)
    current = planner.description(task.id)
    new = len(rollup.ids - listed(current))
    rollup = rollup.keeping(current)
    if task.title == rollup.title and current.strip() == rollup.description.strip():
        return "up to date", new
    if write:
        planner.update_task(task, title=rollup.title, description=rollup.description)
    return ("updated" if write else "to update"), new


def _rollup_cell(state: str) -> render.Cell:
    return (state, "yellow" if state in _ROLLUP_TO_DO else "green")


def _rollup_summary(states: list[str], where: str, *, write: bool) -> str:
    counts = {state: states.count(state) for state in _ROLLUP_STATES}
    if not states:
        return f"no posts in those months, so no rollup for {where}"
    if write:
        return (
            f"raised {counts['raised']} and updated {counts['updated']} rollup(s) in {where}; "
            f"{counts['up to date']} up to date"
        )
    return (
        f"{counts['to raise']} to raise and {counts['to update']} to update in {where}, "
        f"{counts['up to date']} up to date (--write makes the changes)"
    )


_ROLLUP_STATES = ("to raise", "raised", "to update", "updated", "up to date")


def _raise(
    planner: PlannerClient,
    plan: Plan,
    bucket: Bucket,
    message: Message,
    raised: dict[str, Task] | Any,
    *,
    layout: Layout,
    write: bool,
) -> tuple[render.Cell, str]:
    """What happened to one post: it has a task already, it is to raise, or it was raised."""
    if message.id.upper() in raised:
        return ("raised already", "green"), "raised already"
    if not write:
        return ("to raise", "yellow"), "to raise"
    title = task_title(message, layout, limit=TITLE_LIMIT)
    planner.create_task(plan.id, bucket.id, title, description=task_notes(message, layout))
    return ("raised", "green"), "raised"


def _summarise(states: list[str], plan: Plan, bucket: Bucket, said: str, *, write: bool) -> None:
    where = f"{plan.title} / {bucket.name}"
    counts = {state: states.count(state) for state in ("raised already", "to raise", "raised")}
    if write:
        render.note(
            f"raised {counts['raised']} task(s) in {where}; {counts['raised already']} had one"
        )
    else:
        render.note(
            f"{counts['to raise']} to raise in {where}, {counts['raised already']} raised already "
            f"(posts {said}; --write raises them)"
        )


def _task_row(task: Task, names: dict[str, str]) -> list[render.Cell]:
    done: render.Cell = ("done", "green") if task.done else f"{task.percent_complete}%"
    due = render.moment(task.due) if task.due else "-"
    return [
        task.title,
        names.get(task.bucket_id, task.bucket_id),
        done,
        due,
        render.moment(task.created),
        task.id,
    ]


def _task_record(task: Task, names: dict[str, str]) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "bucket": names.get(task.bucket_id) or None,
        "bucket_id": task.bucket_id,
        "percent_complete": task.percent_complete,
        "done": task.done,
        "due": task.due.isoformat() if task.due else None,
        "created": task.created.isoformat() if task.created else None,
        "completed": task.completed.isoformat() if task.completed else None,
    }
