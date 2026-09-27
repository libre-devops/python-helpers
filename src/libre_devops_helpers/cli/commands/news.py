"""``news``: Microsoft 365 Message Center posts, what changes in the tenant's services."""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.markdown import html_to_markdown
from libre_devops_helpers.core.row_filters import day_span
from libre_devops_helpers.core.util import parse_duration
from libre_devops_helpers.microsoft.news import SECURITY_SERVICES, Message

_SEVERITY_COLOURS = {"high": "yellow", "critical": "red"}

news_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Microsoft 365 Message Center: what changes in the tenant's services, and when.",
    no_args_is_help=True,
)

DateOption = Annotated[
    str | None,
    typer.Option(
        "--date",
        help="Only posts changed then: today, 29/09/2026, 2026-09-01..2026-09-14, last 7d, or 7d.",
    ),
]
SinceOption = Annotated[
    str | None, typer.Option("--since", help="Only posts changed in this span, e.g. 7d, 36h.")
]
ServiceOption = Annotated[
    list[str] | None,
    typer.Option(
        "--service",
        help="Only posts for a service whose name holds this, e.g. xdr, Teams. Repeatable.",
    ),
]
SecurityOption = Annotated[
    bool,
    typer.Option(
        "--security",
        help="Only posts for the security services: Defender, Sentinel, Purview, Entra, Intune.",
    ),
]
CategoryOption = Annotated[
    str | None,
    typer.Option(
        "--category",
        help="Only this category: plan for change, stay informed, or prevent or fix issue.",
    ),
]
MajorOption = Annotated[bool, typer.Option("--major", help="Only major changes.")]


def register(app: typer.Typer) -> None:
    """Add the ``news`` commands to ``app``."""
    app.add_typer(news_app, name="news")


def window(
    date_spec: str | None, since: str | None, default: str
) -> tuple[datetime | None, datetime | None, str]:
    """The span of change times asked for: ``--date`` (a day, a span of them, or a length
    of time), else ``--since``, else ``default``; and how to say it."""
    if date_spec and since:
        raise typer.BadParameter("give one of --date and --since", param_hint="--since")
    spec = (date_spec or "").strip()
    if spec and not re.fullmatch(r"\d+[smhd]", spec, re.IGNORECASE):
        first, last = day_span(spec, today=datetime.now(UTC).date())
        start = datetime.combine(first, time.min, UTC) if first else None
        end = datetime.combine(last + timedelta(days=1), time.min, UTC) if last else None
        return start, end, f"changed {spec}"
    span = spec or since or default
    return datetime.now(UTC) - parse_duration(span), None, f"changed in the last {span}"


def services(service: list[str] | None, security: bool) -> tuple[str, ...]:
    """The services a post must be for: those named, and the security ones with --security."""
    return (*(service or ()), *(SECURITY_SERVICES if security else ()))


@news_app.command("messages")
def messages(
    ctx: typer.Context,
    date: DateOption = None,
    since: SinceOption = None,
    service: ServiceOption = None,
    security: SecurityOption = False,
    category: CategoryOption = None,
    major: MajorOption = False,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 100,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Message Center posts, the most recently changed first: the last 30 days by default.

    Needs ServiceMessage.Read.All, which the Azure CLI's token lacks: use a profile with
    your own app registration.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    start, end, said = window(date, since, "30d")
    found = runtime.news(selected).messages(
        since=start,
        until=end,
        services=services(service, security),
        category=category,
        major=major,
        limit=limit,
    )
    render.emit(
        output,
        ["ID", "UPDATED", "CATEGORY", "SEVERITY", "SERVICES", "ACTION BY", "TITLE"],
        [_row(message) for message in found],
        [record(message) for message in found],
    )
    render.note(f"{len(found)} post(s) {said} (profile {selected.name})")


@news_app.command("message")
def message(
    ctx: typer.Context,
    message_id: Annotated[str, typer.Argument(metavar="ID", help="The post's id, e.g. MC1183010.")],
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Only the post, as Markdown.")
    ] = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """One post: what changes, for which services, by when, and all it says, as Markdown."""
    runtime = get_runtime(ctx).microsoft
    found = runtime.news(runtime.profile(profile)).message(message_id)
    body = html_to_markdown(found.body_html).strip() if found.body_html else ""
    if markdown:
        render.echo(body)
        return
    pairs = [
        ("Id", found.id),
        ("Title", found.title),
        ("Category", found.category_label),
        ("Severity", found.severity),
        ("Major change", render.yes_no(found.major)),
        ("Services", ", ".join(found.services) or "-"),
        ("Tags", ", ".join(found.tags) or "-"),
        ("Starts", render.moment(found.starts)),
        ("Action by", render.moment(found.action_by)),
        ("Updated", render.moment(found.updated)),
        ("Link", found.url),
    ]
    if output is Output.TABLE:
        render.echo(render.pairs(pairs))
        render.echo()
        render.echo(body or "(no text)")
        return
    headers = [label.upper() for label, _ in pairs] + ["BODY"]
    render.emit(
        output,
        headers,
        [[value for _, value in pairs] + [body]],
        {**record(found), "body": body or None},
    )


def _row(found: Message) -> list[render.Cell]:
    severity: render.Cell = (found.severity, _SEVERITY_COLOURS.get(found.severity.casefold()))
    title = f"{found.title} (major)" if found.major else found.title
    return [
        found.id,
        render.when(found.updated),
        found.category_label,
        severity,
        ", ".join(found.services),
        render.moment(found.action_by) if found.action_by else "-",
        title,
    ]


def record(found: Message) -> dict[str, Any]:
    """A post as ``-o json`` gives it."""
    return {
        "id": found.id,
        "title": found.title,
        "category": found.category,
        "severity": found.severity,
        "services": list(found.services),
        "tags": list(found.tags),
        "major": found.major,
        "starts": found.starts.isoformat() if found.starts else None,
        "ends": found.ends.isoformat() if found.ends else None,
        "updated": found.updated.isoformat() if found.updated else None,
        "action_by": found.action_by.isoformat() if found.action_by else None,
        "url": found.url,
    }
