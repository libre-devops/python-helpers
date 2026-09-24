"""Graph commands: who am I, a token, any GET, objects by name, and Advanced Hunting.

A fast way to read Microsoft Graph with a profile's sign-in, as ``az rest`` would, but
knowing Graph: paging (``--all``, ``--limit``), its query options, ``ConsistencyLevel``
for ``--count`` and ``--search``, v1.0 or ``--beta``, and output as a table, JSON or CSV.
Everything reads; there is no POST, PATCH or DELETE.
"""

import json
from datetime import datetime
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands import token as token_commands
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    QueryFileOption,
    duration,
    get_runtime,
    read_query,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import AmbiguousError, ApiError
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.microsoft.graph import not_found
from libre_devops_helpers.microsoft.resources import resolve_resource
from libre_devops_helpers.microsoft.tokens import decode_token

graph_app = typer.Typer(
    rich_markup_mode="markdown",
    name="graph",
    help="Microsoft Graph: whoami, a token, any GET, objects by name, and hunting.",
    no_args_is_help=True,
)

# Shown first for an object, when it has them; everything else follows.
_FIRST = (
    "id",
    "displayName",
    "userPrincipalName",
    "mail",
    "appId",
    "deviceId",
    "operatingSystem",
    "accountEnabled",
    "createdDateTime",
)


def register(app: typer.Typer) -> None:
    app.add_typer(graph_app)


BetaOption = Annotated[bool, typer.Option("--beta", help="Use Graph's beta endpoint.")]
SelectOption = Annotated[
    str | None,
    typer.Option("--select", help="Properties to return, e.g. id,displayName ($select)."),
]


@graph_app.command("whoami")
def whoami(
    ctx: typer.Context, profile: ProfileOption = None, output: OutputOption = Output.TABLE
) -> None:
    """Who the profile's Graph token is for, what it may do, and when it expires."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    target = resolve_resource("graph", selected.cloud)
    decoded = decode_token(runtime.tokens(selected).get_token(target.url, selected.tenant_id).token)
    graph = runtime.graph(selected)
    kind = decoded.identity_type
    detail: dict[str, Any] | None = None
    try:
        detail = graph.me() if kind == "user" else graph.service_principal(decoded.app_id)
    except ApiError as exc:
        render.warn(f"could not read the {'user' if kind == 'user' else 'app'}: {exc}")
    permissions = decoded.scopes if kind == "user" else decoded.roles
    record = {
        "profile": selected.name,
        "tenant_id": decoded.tenant_id,
        "kind": kind,
        "principal": decoded.principal,
        "client_app_id": decoded.app_id,
        "client_app": decoded.claims.get("app_displayname"),
        "expires_at": decoded.expires_at.isoformat() if decoded.expires_at else None,
        "scopes": list(decoded.scopes),
        "roles": list(decoded.roles),
        "object": detail,
    }
    if output is not Output.TABLE:
        render.emit(
            output,
            ["PROFILE", "KIND", "PRINCIPAL", "TENANT", "EXPIRES", "PERMISSIONS"],
            [
                [
                    selected.name,
                    kind,
                    decoded.principal,
                    decoded.tenant_id,
                    render.when(decoded.expires_at),
                    " ".join(permissions),
                ]
            ],
            record,
        )
        return
    rows = [
        ("Profile", f"{selected.name} ({selected.auth})"),
        ("Signed in as", decoded.principal or "-"),
        ("Kind", "user (delegated)" if kind == "user" else f"{kind} (application)"),
    ]
    if detail:
        rows.append(("Name", str(detail.get("displayName") or "-")))
        rows.append(("Object id", str(detail.get("id") or "-")))
        if detail.get("jobTitle"):
            rows.append(("Job title", str(detail["jobTitle"])))
    rows += [
        ("Tenant", decoded.tenant_id),
        ("Client app", f"{decoded.claims.get('app_displayname') or '-'} ({decoded.app_id})"),
        ("Expires", render.when(decoded.expires_at)),
        (
            "Scopes" if kind == "user" else "Roles",
            ", ".join(sorted(permissions)) or "(none)",
        ),
    ]
    render.echo(render.pairs(rows))


@graph_app.command("token")
def token(
    ctx: typer.Context,
    profile: ProfileOption = None,
    raw: Annotated[
        bool, typer.Option("--raw", help="Print only the token, for piping. Still checked first.")
    ] = False,
    require: token_commands.RequireOption = None,
    strict: token_commands.StrictOption = False,
    all_claims: token_commands.AllClaimsOption = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Get a Graph token and check it: which of this tool's features it covers.

    The same as 'entra token graph'. The token itself is printed only with --raw, e.g.
    curl -H "Authorization: Bearer $(ldo graph token --raw)" ...
    """
    token_commands.token(
        ctx,
        "graph",
        profile=profile,
        raw=raw,
        require=require,
        strict=strict,
        all_claims=all_claims,
        output=output,
    )


@graph_app.command("get")
def get(
    ctx: typer.Context,
    path: Annotated[
        str,
        typer.Argument(help="A Graph path (users, me/memberOf, beta/...) or a full Graph URL."),
    ],
    select: SelectOption = None,
    filter_: Annotated[
        str | None, typer.Option("--filter", help="An OData filter ($filter).")
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", help='A $search, e.g. "displayName:ana" (sets ConsistencyLevel).'),
    ] = None,
    orderby: Annotated[str | None, typer.Option("--orderby", help="$orderby.")] = None,
    expand: Annotated[str | None, typer.Option("--expand", help="$expand.")] = None,
    top: Annotated[int | None, typer.Option("--top", min=1, help="Page size ($top).")] = None,
    count: Annotated[
        bool, typer.Option("--count", help="Ask for the total count (sets ConsistencyLevel).")
    ] = False,
    eventual: Annotated[
        bool,
        typer.Option("--eventual", help="Send ConsistencyLevel: eventual, for advanced queries."),
    ] = False,
    all_pages: Annotated[bool, typer.Option("--all", help="Follow every page.")] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", min=1, help="Stop after this many items.")
    ] = None,
    beta: BetaOption = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """GET anything from Graph, paged. Collections come back as rows, objects as fields.

    Without --all or --limit, one page is shown, and a note says when there are more.
    """
    params = {
        key: value
        for key, value in (
            ("$select", select),
            ("$filter", filter_),
            ("$search", _quoted(search)),
            ("$orderby", orderby),
            ("$expand", expand),
            ("$top", str(top) if top else None),
            ("$count", "true" if count else None),
        )
        if value
    }
    runtime = get_runtime(ctx).microsoft
    graph = runtime.graph(runtime.profile(profile))
    advanced = eventual or count or bool(search)
    data = graph.get(path, params=params, beta=beta, eventual=advanced)
    if not isinstance(data.get("value"), list):
        _show_object(data, output)
        return
    page = graph.page(
        path, params=params, beta=beta, eventual=advanced, limit=limit, all_pages=all_pages
    )
    columns = [name.strip() for name in select.split(",")] if select else None
    _show_items(list(page.items), output, columns)
    note = f"{len(page.items)} item(s)"
    if page.count is not None:
        note += f" of {page.count}"
    if page.more:
        note += "; more exist (--all, or --limit N)"
    render.note(note)


def _lookup_command(kind: str, what: str):
    def command(
        ctx: typer.Context,
        ref: Annotated[str, typer.Argument(metavar="NAME_OR_ID", help=f"The {what}'s name or id.")],
        select: SelectOption = None,
        profile: ProfileOption = None,
        output: OutputOption = Output.TABLE,
    ) -> None:
        runtime = get_runtime(ctx).microsoft
        graph = runtime.graph(runtime.profile(profile))
        found = graph.lookup(kind, ref, select=select)
        if not found:
            raise not_found(kind, ref)
        if len(found) == 1:
            _show_object(found[0], output)
            return
        if kind not in {"device"}:
            ids = ", ".join(str(item.get("id")) for item in found)
            raise AmbiguousError(
                f"{len(found)} {what}s are named {ref!r}", hint=f"use an id instead: {ids}"
            )
        # Stale registrations keep a device's name, so every match is shown.
        _show_items(found, output, None)
        render.warn(f"{len(found)} devices are named {ref!r}")

    command.__doc__ = f"One {what}, by name or id, with every property Graph returns."
    return command


graph_app.command("get-user")(_lookup_command("user", "user"))
graph_app.command("get-device")(_lookup_command("device", "device"))
graph_app.command("get-group")(_lookup_command("group", "group"))
graph_app.command("get-app")(_lookup_command("app", "app registration"))
graph_app.command("get-sp")(_lookup_command("sp", "service principal"))


@graph_app.command("hunt")
def hunt(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(
            help="KQL query. Omit, or pass -, to read it from stdin.", show_default=False
        ),
    ] = None,
    file: QueryFileOption = None,
    timespan: Annotated[
        str | None,
        typer.Option("--timespan", help="How far back the data goes, e.g. 7d. Default: 30 days."),
    ] = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Advanced Hunting (KQL) over the whole Defender XDR schema, through Graph.

    Email, identity, cloud app and alert tables as well as the device ones. Needs
    ThreatHunting.Read.All: an interactive or device-code profile whose app has it.
    """
    run_graph_hunt(ctx, read_query(query, file), timespan, profile, output)


def run_graph_hunt(
    ctx: typer.Context, text: str, timespan: str | None, profile: str | None, output: Output
) -> None:
    """Shared by 'graph hunt' and 'xdr hunt', which default to Graph."""
    runtime = get_runtime(ctx).microsoft
    result: QueryResult = runtime.graph(runtime.profile(profile)).hunt(
        text, timespan=duration(timespan)
    )
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")


# Rendering -------------------------------------------------------------------------------


def _show_object(data: dict[str, Any], output: Output) -> None:
    record = {key: value for key, value in data.items() if not key.startswith("@odata")}
    if output is not Output.TABLE:
        render.emit(output, list(record), [[_cell(value) for value in record.values()]], record)
        return
    ordered = [key for key in _FIRST if key in record] + [
        key for key in record if key not in _FIRST
    ]
    render.echo(render.pairs((key, _cell(record[key])) for key in ordered))


def _show_items(items: list[dict[str, Any]], output: Output, columns: list[str] | None) -> None:
    if output is Output.JSON:
        render.print_json(items)
        return
    if columns is None:
        seen: dict[str, None] = {}
        for item in items:
            for key in item:
                if not key.startswith("@odata"):
                    seen.setdefault(key)
        columns = list(seen)
        if output is Output.TABLE:
            # A table of every property is too wide to read: the familiar ones, or eight.
            familiar = [key for key in _FIRST if key in seen]
            columns = familiar or columns[:8]
    render.emit(
        output,
        [column.upper() for column in columns],
        [[_cell(item.get(column)) for column in columns] for item in items],
        items,
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value).lower() if isinstance(value, bool) else str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return json.dumps(value)


def _quoted(search: str | None) -> str | None:
    """Graph wants $search in double quotes; add them when they are missing."""
    if not search:
        return None
    text = search.strip()
    return text if text.startswith('"') else f'"{text}"'
