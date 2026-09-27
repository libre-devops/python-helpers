"""``jira``: Jira Cloud issues and projects, read with an Atlassian API token."""

import re
from typing import Annotated, Any

import typer

from libre_devops_helpers.atlassian.jira import DEFAULT_JQL, Issue
from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    AtlassianProfileOption,
    OutputOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output

_PROJECT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,254}")
_CATEGORY_COLOURS = {"Done": "green", "In Progress": "yellow"}

jira_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Jira Cloud: issues by JQL, one issue with its description, and projects.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the ``jira`` commands to ``app``."""
    app.add_typer(jira_app, name="jira")


@jira_app.command("whoami")
def whoami(
    ctx: typer.Context, profile: AtlassianProfileOption = None, output: OutputOption = Output.TABLE
) -> None:
    """Who the profile's API token reads Jira as, and on which site."""
    atlassian = get_runtime(ctx).atlassian
    selected = atlassian.profile(profile)
    me = atlassian.jira(selected).whoami()
    record = {
        "profile": selected.name,
        "site": selected.site,
        "account_id": me.get("accountId"),
        "name": me.get("displayName"),
        "email": me.get("emailAddress") or selected.email,
        "active": me.get("active"),
        "time_zone": me.get("timeZone"),
    }
    pairs = [
        ("Profile", selected.name),
        ("Site", selected.site),
        ("Name", str(record["name"] or "")),
        ("Email", str(record["email"] or "")),
        ("Account id", str(record["account_id"] or "")),
        ("Active", render.yes_no(record["active"] if isinstance(record["active"], bool) else None)),
    ]
    if output is Output.TABLE:
        render.echo(render.pairs(pairs))
        return
    render.emit(
        output, [label.upper() for label, _ in pairs], [[value for _, value in pairs]], record
    )


@jira_app.command("issues")
def issues(
    ctx: typer.Context,
    jql: Annotated[
        str | None,
        typer.Argument(help="A JQL query. Default: the issues not done, newest change first."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Only this project's issues not done (instead of a query)."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 50,
    profile: AtlassianProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Issues a JQL query finds, as Jira orders them.

    Jira refuses a query with no restriction at all, so give one (a project, a status, a
    date): without a query, it is the issues not done.
    """
    atlassian = get_runtime(ctx).atlassian
    selected = atlassian.profile(profile)
    found = atlassian.jira(selected).issues(_query(jql, project), limit=limit)
    render.emit(
        output,
        ["KEY", "TYPE", "STATUS", "PRIORITY", "ASSIGNEE", "UPDATED", "SUMMARY"],
        [_issue_row(issue) for issue in found],
        [_issue_record(issue) for issue in found],
    )
    render.note(f"{len(found)} issue(s) (profile {selected.name})")


@jira_app.command("issue")
def issue(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="The issue's key, e.g. OPS-123.")],
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Only the description, as Markdown.")
    ] = False,
    profile: AtlassianProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """One issue: what it is, where it stands, who has it, and its description as Markdown."""
    atlassian = get_runtime(ctx).atlassian
    found = atlassian.jira(atlassian.profile(profile)).issue(key)
    if markdown:
        render.echo(found.description)
        return
    pairs = [
        ("Key", found.key),
        ("Summary", found.summary),
        ("Type", found.type),
        ("Status", f"{found.status} ({found.status_category})"),
        ("Priority", found.priority or "-"),
        ("Assignee", found.assignee or "unassigned"),
        ("Reporter", found.reporter),
        ("Created", render.moment(found.created)),
        ("Updated", render.moment(found.updated)),
        ("Labels", ", ".join(found.labels) or "-"),
        ("Link", found.url),
    ]
    if output is Output.TABLE:
        render.echo(render.pairs(pairs))
        render.echo()
        render.echo(found.description or "(no description)")
        return
    record = {**_issue_record(found), "description": found.description or None}
    headers = [label.upper() for label, _ in pairs] + ["DESCRIPTION"]
    render.emit(output, headers, [[value for _, value in pairs] + [found.description]], record)


@jira_app.command("projects")
def projects(
    ctx: typer.Context,
    profile: AtlassianProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The projects the account can see."""
    atlassian = get_runtime(ctx).atlassian
    found = atlassian.jira(atlassian.profile(profile)).projects()
    render.emit(
        output,
        ["KEY", "NAME", "TYPE", "LINK"],
        [[item.key, item.name, item.type, item.url] for item in found],
        [
            {"key": item.key, "id": item.id, "name": item.name, "type": item.type, "url": item.url}
            for item in found
        ],
    )


def _query(jql: str | None, project: str | None) -> str:
    if jql and project:
        raise typer.BadParameter("put the project in the query instead", param_hint="--project")
    if project:
        if not _PROJECT.fullmatch(project.strip()):
            raise typer.BadParameter(f"{project!r} is not a project key", param_hint="--project")
        return f"project = {project.strip().upper()} AND {DEFAULT_JQL}"
    return jql.strip() if jql and jql.strip() else DEFAULT_JQL


def _issue_row(issue: Issue) -> list[render.Cell]:
    status: render.Cell = (issue.status, _CATEGORY_COLOURS.get(issue.status_category))
    return [
        issue.key,
        issue.type,
        status,
        issue.priority,
        issue.assignee or "-",
        render.when(issue.updated),
        issue.summary,
    ]


def _issue_record(issue: Issue) -> dict[str, Any]:
    return {
        "key": issue.key,
        "id": issue.id,
        "summary": issue.summary,
        "type": issue.type,
        "status": issue.status,
        "status_category": issue.status_category,
        "priority": issue.priority or None,
        "assignee": issue.assignee or None,
        "reporter": issue.reporter or None,
        "project": issue.project,
        "labels": list(issue.labels),
        "created": issue.created.isoformat() if issue.created else None,
        "updated": issue.updated.isoformat() if issue.updated else None,
        "url": issue.url,
    }
