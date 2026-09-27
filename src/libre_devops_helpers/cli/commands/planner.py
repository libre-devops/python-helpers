"""``planner``: Microsoft Planner plans and tasks, and raising a task for each Message Center
post a plan does not have one for yet."""

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
from libre_devops_helpers.core.markdown import html_to_markdown
from libre_devops_helpers.microsoft.news import MESSAGE_KEY, Message
from libre_devops_helpers.microsoft.planner import Bucket, Plan, PlannerClient, Task, keyed

# A task's description holds the post's link and its text, up to this much of it.
_DESCRIPTION_LIMIT = 6000

planner_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Microsoft Planner: plans, buckets and tasks, and a task for each Message Center post.",
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
    starting with its id: MC1183010: and its title, as these are raised. Without --write
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
    outcomes = [_raise(planner, chosen, column, item, raised, write=write) for item in found]
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


def _raise(
    planner: PlannerClient,
    plan: Plan,
    bucket: Bucket,
    message: Message,
    raised: dict[str, Task] | Any,
    *,
    write: bool,
) -> tuple[render.Cell, str]:
    """What happened to one post: it has a task already, it is to raise, or it was raised."""
    if message.id.upper() in raised:
        return ("raised already", "green"), "raised already"
    if not write:
        return ("to raise", "yellow"), "to raise"
    planner.create_task(plan.id, bucket.id, message.task_title, description=_description(message))
    return ("raised", "green"), "raised"


def _description(message: Message) -> str:
    body = html_to_markdown(message.body_html).strip() if message.body_html else ""
    if len(body) > _DESCRIPTION_LIMIT:
        body = body[:_DESCRIPTION_LIMIT].rstrip() + "\n\n(more in the admin centre)"
    return f"{message.url}\n\n{body}".strip()


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
