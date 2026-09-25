"""Logic Apps in Azure: export deployed workflows, and ask the provider to validate one.

Both only read. validate sends a definition to the provider's validate action, which
checks it as a deployment would and creates nothing.
"""

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.commands.logicapp.local import record
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.logicapps import load


def register(app: typer.Typer) -> None:
    """Add ``export`` and ``validate`` to ``app``."""
    app.command("export")(export)
    app.command("validate")(validate)


ResourceGroupOption = Annotated[
    str, typer.Option("--resource-group", "-g", help="The resource group.", show_default=False)
]

SubscriptionOption = Annotated[
    str | None,
    typer.Option(
        "--subscription",
        "-s",
        help="Subscription id. Default: the profile's, or its only one.",
        show_default=False,
    ),
]


def export(
    ctx: typer.Context,
    resource_group: ResourceGroupOption,
    out: Annotated[Path, typer.Option("--out", help="The folder to write into.", file_okay=False)],
    name: Annotated[
        list[str] | None,
        typer.Option("--name", help="Only this workflow. Repeatable.", show_default=False),
    ] = None,
    shape: Annotated[
        str,
        typer.Option(
            "--shape", help="code-view (definition and values) or arm (the whole resource)."
        ),
    ] = "code-view",
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Export deployed workflows to files, one per workflow. Reads Azure; writes only files."""
    if shape not in {"code-view", "arm"}:
        raise typer.BadParameter("--shape must be code-view or arm")
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    sub = _subscription(runtime, selected, subscription)
    client = runtime.logicapps(selected)
    wanted = {item.casefold() for item in name or ()}
    listed = [
        item
        for item in client.workflows(sub, resource_group)
        if not wanted or str(item.get("name", "")).casefold() in wanted
    ]
    if not listed:
        render.warn(f"no Logic App workflows matched in {resource_group}")
        return
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in listed:
        workflow = str(item["name"])
        resource = client.workflow(sub, resource_group, workflow)
        document: dict[str, Any] = resource
        if shape == "code-view":
            properties = resource.get("properties") or {}
            document = {"definition": properties.get("definition")}
            if "parameters" in properties:
                document["parameters"] = properties["parameters"]
        path = out / f"{workflow}.json"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        rows.append(
            {"workflow": workflow, "id": resource.get("id"), "shape": shape, "path": str(path)}
        )
    render.emit(
        output,
        ["WORKFLOW", "PATH"],
        [[str(row["workflow"]), str(row["path"])] for row in rows],
        rows,
    )
    render.note(f"exported {len(rows)} workflow(s) to {out}")


def validate(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="The definition, in any of the three shapes.")],
    resource_group: ResourceGroupOption,
    location: Annotated[
        str | None,
        typer.Option("--location", help="Region, e.g. uksouth. Default: the resource group's."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Workflow name for the call. Default: from the file."),
    ] = None,
    subscription: SubscriptionOption = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Ask Azure whether it would accept a definition, without deploying anything.

    The provider's own verdict: it type-checks the whole definition and creates nothing.
    Exits 3 when it is rejected.
    """
    document = load(file)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    sub = _subscription(runtime, selected, subscription)
    client = runtime.logicapps(selected)
    region = location or client.location_of(sub, resource_group)
    verdict = client.validate(
        document, subscription=sub, resource_group=resource_group, location=region, name=name
    )
    render.emit(
        output,
        ["WORKFLOW", "LOCATION", "VALID", "MESSAGE"],
        [
            [
                verdict.workflow,
                verdict.location,
                ("yes", "green") if verdict.valid else ("no", "red"),
                verdict.message,
            ]
        ],
        record(verdict),
    )
    if not verdict.valid:
        raise typer.Exit(ATTENTION)


def _subscription(runtime: MicrosoftRuntime, profile: Profile, given: str | None) -> str:
    if given:
        return given
    if profile.subscription_id:
        return profile.subscription_id
    found = runtime.subscription_ids(profile)
    if len(found) == 1:
        return found[0]
    raise InputError(
        f"profile {profile.name!r} can see {len(found)} subscriptions",
        hint="pass --subscription, or pin the profile to one",
    )
