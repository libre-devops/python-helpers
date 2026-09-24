"""Azure commands: subscriptions, Resource Graph, RBAC and Defender for Cloud."""

from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    QueryFileOption,
    get_runtime,
    read_query,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.util import is_guid

azure_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Azure: subscriptions, Resource Graph, RBAC and Defender for Cloud.",
    no_args_is_help=True,
)

SubscriptionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--subscription",
        "-s",
        help="Subscription id to cover. Repeatable. Default: the profile's subscription, "
        "else every one in the tenant.",
        show_default=False,
    ),
]


def register(app: typer.Typer) -> None:
    app.add_typer(azure_app, name="azure")


@azure_app.command("subscriptions")
def subscriptions(
    ctx: typer.Context, profile: ProfileOption = None, output: OutputOption = Output.TABLE
) -> None:
    """List the subscriptions the profile's credential can see in its tenant."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    found = runtime.azure(selected).subscriptions(selected.tenant_id)
    render.emit(
        output,
        ["SUBSCRIPTION", "ID", "STATE"],
        [[item.name, item.id, item.state] for item in found],
        [dict(item.raw) for item in found],
    )


@azure_app.command("resource-graph")
def resource_graph(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(
            help="KQL query. Omit, or pass -, to read it from stdin.", show_default=False
        ),
    ] = None,
    file: QueryFileOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most rows to fetch.")] = 1000,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run an Azure Resource Graph (KQL) query across subscriptions."""
    text = read_query(query, file)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    scope = subscription or ([selected.subscription_id] if selected.subscription_id else [])
    result = runtime.azure(selected).resource_graph(text, subscriptions=scope, limit=limit)
    render.query_result(result, output)
    render.note(f"{len(result.rows)} row(s)")


@azure_app.command("rbac")
def rbac(
    ctx: typer.Context,
    principal: Annotated[
        str,
        typer.Argument(help="User principal name, group or service principal name, or object id."),
    ],
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List every Azure role assignment that applies to a principal, across subscriptions.

    Includes assignments made to groups the principal is in, and those inherited from
    management groups.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    if is_guid(principal):
        principal_id, label = principal.strip().lower(), principal
    else:
        found = runtime.entra(selected).find_principal(principal)
        principal_id, label = found.id, f"{found.display_name} ({found.kind})"
    subscriptions = runtime.subscription_ids(selected, subscription)
    assignments = runtime.azure(selected).role_assignments(principal_id, subscriptions)
    if output is Output.TABLE:
        render.echo(render.title(f"{label}  object {principal_id}"))
    render.emit(
        output,
        ["ROLE", "SCOPE", "ASSIGNED TO", "CONDITION"],
        [
            [
                item.role_name,
                item.scope,
                "this principal"
                if item.principal_id.lower() == principal_id
                else f"{item.principal_type} {item.principal_id}",
                "yes" if item.condition else "",
            ]
            for item in assignments
        ],
        [dict(item.raw) | {"roleName": item.role_name} for item in assignments],
    )
    render.note(f"{len(assignments)} assignment(s) across {len(subscriptions)} subscription(s)")


@azure_app.command("secure-score")
def secure_score(
    ctx: typer.Context,
    controls: Annotated[
        bool, typer.Option("--controls", help="Also list the controls costing the most points.")
    ] = False,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Show the Defender for Cloud secure score for each subscription."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    azure = runtime.azure(selected)
    scores = [azure.secure_score(item) for item in runtime.subscription_ids(selected, subscription)]
    found = [score for score in scores if score is not None]
    render.emit(
        output,
        ["SUBSCRIPTION", "SCORE", "MAX", "PERCENT"],
        [
            [
                score.subscription_id,
                _number(score.current),
                _number(score.max),
                "" if score.percentage is None else f"{score.percentage * 100:.0f}%",
            ]
            for score in found
        ],
        [dict(score.raw) for score in found],
    )
    if len(found) < len(scores):
        render.warn(f"{len(scores) - len(found)} subscription(s) have no secure score")
    if controls and output is not Output.JSON:
        for score in found:
            render.echo()
            render.echo(render.title(f"controls for {score.subscription_id}"))
            items = azure.secure_score_controls(score.subscription_id)
            render.emit(
                output,
                ["CONTROL", "POINTS LOST", "SCORE", "MAX", "UNHEALTHY", "HEALTHY"],
                [
                    [
                        item.name,
                        f"{item.points_lost:.2f}",
                        _number(item.current),
                        _number(item.max),
                        str(item.unhealthy),
                        str(item.healthy),
                    ]
                    for item in items
                    if item.max
                ],
                None,
            )


@azure_app.command("recommendations")
def recommendations(
    ctx: typer.Context,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include healthy and not applicable results.")
    ] = False,
    severity: Annotated[
        str | None, typer.Option("--severity", help="Only this severity: high, medium or low.")
    ] = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List Defender for Cloud recommendations that resources fail, most severe first."""
    if severity is not None and severity.casefold() not in {"high", "medium", "low"}:
        raise typer.BadParameter("--severity must be high, medium or low")
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    azure = runtime.azure(selected)
    found = [
        item
        for sub in runtime.subscription_ids(selected, subscription)
        for item in azure.assessments(sub, unhealthy_only=not show_all)
        if severity is None or item.severity.casefold() == severity.casefold()
    ]
    colours = {"high": "red", "medium": "yellow"}
    render.emit(
        output,
        ["SEVERITY", "STATUS", "RECOMMENDATION", "RESOURCE"],
        [
            [
                (item.severity, colours.get(item.severity.casefold())),
                item.status,
                item.name,
                item.resource_id,
            ]
            for item in found
        ],
        [dict(item.raw) for item in found],
    )
    render.note(f"{len(found)} result(s)")


@azure_app.command("defender-plans")
def defender_plans(
    ctx: typer.Context,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List every Defender for Cloud plan on each subscription and whether it is on."""
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    azure = runtime.azure(selected)
    rows: list[list[render.Cell]] = []
    records: list[dict[str, object]] = []
    for sub in runtime.subscription_ids(selected, subscription):
        for plan in azure.defender_plans(sub):
            rows.append(
                [
                    sub,
                    plan.name,
                    ("on", "green") if plan.enabled else ("off", "yellow"),
                    plan.sub_plan,
                    render.when(plan.enabled_since) if plan.enabled_since else "",
                    "deprecated" if plan.deprecated else "",
                ]
            )
            records.append({"subscriptionId": sub, **plan.raw})
    render.emit(
        output, ["SUBSCRIPTION", "PLAN", "STATE", "SUB PLAN", "SINCE", "NOTE"], rows, records
    )


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"
