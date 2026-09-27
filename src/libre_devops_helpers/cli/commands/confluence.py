"""``confluence``: Confluence Cloud spaces, pages and search, read with an Atlassian API token."""

from typing import Annotated, Any

import typer

from libre_devops_helpers.atlassian.confluence import Page
from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    AtlassianProfileOption,
    OutputOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output

confluence_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Confluence Cloud: spaces, pages (as Markdown) and CQL search.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the ``confluence`` commands to ``app``."""
    app.add_typer(confluence_app, name="confluence")


@confluence_app.command("spaces")
def spaces(
    ctx: typer.Context,
    profile: AtlassianProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The spaces the account can see."""
    atlassian = get_runtime(ctx).atlassian
    found = atlassian.confluence(atlassian.profile(profile)).spaces()
    render.emit(
        output,
        ["KEY", "NAME", "TYPE", "STATUS", "LINK"],
        [[space.key, space.name, space.type, space.status, space.url] for space in found],
        [
            {
                "key": space.key,
                "id": space.id,
                "name": space.name,
                "type": space.type,
                "status": space.status,
                "url": space.url or None,
            }
            for space in found
        ],
    )


@confluence_app.command("pages")
def pages(
    ctx: typer.Context,
    space: Annotated[
        str | None, typer.Option("--space", help="Only this space's pages, by key.")
    ] = None,
    title: Annotated[
        str | None, typer.Option("--title", help="Only pages with this exact title.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 50,
    profile: AtlassianProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Pages, the most recently changed first: every space's, or one's."""
    atlassian = get_runtime(ctx).atlassian
    confluence = atlassian.confluence(atlassian.profile(profile))
    found = confluence.pages(space=space, title=title, limit=limit)
    keys = {item.id: item.key for item in confluence.spaces()} if found else {}
    render.emit(
        output,
        ["ID", "TITLE", "SPACE", "VERSION", "UPDATED", "LINK"],
        [
            [
                page.id,
                page.title,
                keys.get(page.space_id, page.space_id),
                str(page.version),
                render.when(page.updated),
                page.url,
            ]
            for page in found
        ],
        [_page_record(page, keys.get(page.space_id)) for page in found],
    )


@confluence_app.command("page")
def page(
    ctx: typer.Context,
    page_id: Annotated[
        str, typer.Argument(metavar="ID", help="The page's id: the number in its link.")
    ],
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Only the page, as Markdown.")
    ] = False,
    profile: AtlassianProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """One page: its title, where it is, its version, and its body as Markdown."""
    atlassian = get_runtime(ctx).atlassian
    found = atlassian.confluence(atlassian.profile(profile)).page(page_id)
    if markdown:
        render.echo(found.body)
        return
    pairs = [
        ("Title", found.title),
        ("Id", found.id),
        ("Version", str(found.version)),
        ("Updated", render.moment(found.updated)),
        ("Link", found.url),
    ]
    if output is Output.TABLE:
        render.echo(render.pairs(pairs))
        render.echo()
        render.echo(found.body or "(an empty page)")
        return
    headers = [label.upper() for label, _ in pairs] + ["BODY"]
    record = {**_page_record(found, None), "body": found.body or None}
    render.emit(output, headers, [[value for _, value in pairs] + [found.body]], record)


@confluence_app.command("search")
def search(
    ctx: typer.Context,
    cql: Annotated[str, typer.Argument(help='A CQL query, e.g. type = page AND text ~ "runbook".')],
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 25,
    profile: AtlassianProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """What a CQL query finds: pages, blog posts, attachments."""
    atlassian = get_runtime(ctx).atlassian
    found = atlassian.confluence(atlassian.profile(profile)).search(cql, limit=limit)
    render.emit(
        output,
        ["TYPE", "TITLE", "SPACE", "UPDATED", "LINK"],
        [[hit.type, hit.title, hit.space, render.when(hit.updated), hit.url] for hit in found],
        [
            {
                "id": hit.id or None,
                "type": hit.type,
                "title": hit.title,
                "space": hit.space or None,
                "updated": hit.updated.isoformat() if hit.updated else None,
                "url": hit.url or None,
                "excerpt": hit.excerpt or None,
            }
            for hit in found
        ],
    )


def _page_record(page: Page, space: str | None) -> dict[str, Any]:
    return {
        "id": page.id,
        "title": page.title,
        "space_id": page.space_id,
        "space": space,
        "status": page.status,
        "version": page.version,
        "updated": page.updated.isoformat() if page.updated else None,
        "url": page.url or None,
    }
