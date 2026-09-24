"""Logic App commands: check, audit and compare workflow definitions; read and validate them.

The offline commands (check, params, references, connections, order, diff, defaults,
rewrite) read files and never touch the network; they take files or folders, and a
folder means every .json and .json.tftpl in it. export and validate go to Azure, and
only read: validate asks the provider for its verdict and creates nothing.
"""

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import OutputOption, ProfileOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.logicapps import (
    WorkflowDocument,
    check,
    compare,
    connection_references,
    connections_of,
    deploy_order,
    load,
    parameter_status,
    rewrite_references,
    with_parameter_defaults,
)

logicapp_app = typer.Typer(
    rich_markup_mode="markdown",
    name="logicapp",
    help="Consumption Logic Apps: check, audit, compare, export and validate workflows.",
    no_args_is_help=True,
)

_SEVERITY_COLOURS = {"error": "red", "warning": "yellow"}


def register(app: typer.Typer) -> None:
    app.add_typer(logicapp_app)


FilesArgument = Annotated[
    list[Path],
    typer.Argument(
        help="Definition files (.json, .json.tftpl), or folders of them.", show_default=False
    ),
]
SuppliedOption = Annotated[
    list[str] | None,
    typer.Option(
        "--supplied",
        help="A parameter the deployment tool supplies (a Terraform parameters input). Repeatable.",
        show_default=False,
    ),
]
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
OutFileOption = Annotated[
    Path | None,
    typer.Option(
        "--out", help="Write here instead of printing.", dir_okay=False, show_default=False
    ),
]


@logicapp_app.command("check")
def check_command(
    files: FilesArgument,
    supplied: SuppliedOption = None,
    connection: Annotated[
        list[str] | None,
        typer.Option(
            "--connection",
            help="A connection key the deployment wires. Repeatable.",
            show_default=False,
        ),
    ] = None,
    callback_trigger: Annotated[
        str | None,
        typer.Option("--callback-trigger", help="A trigger that must exist, to be called."),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Warnings fail the check too.")] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Check definitions offline against what Azure rejects, or what fails once it runs.

    Exits 3 when any definition has an error (or, with --strict, a warning), so a build
    step can gate on it.
    """
    documents = _documents(files)
    findings = [
        finding
        for document in documents
        for finding in check(
            document,
            supplied=supplied or (),
            connections=connection or (),
            callback_trigger=callback_trigger,
        )
    ]
    render.emit(
        output,
        ["WORKFLOW", "SEVERITY", "RULE", "MESSAGE"],
        [
            [
                finding.workflow or finding.source,
                (finding.severity, _SEVERITY_COLOURS.get(finding.severity)),
                finding.rule,
                finding.message,
            ]
            for finding in findings
        ],
        [_record(finding) for finding in findings],
    )
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = len(findings) - errors
    render.note(f"{len(documents)} definition(s): {errors} error(s), {warnings} warning(s)")
    if errors or (strict and warnings):
        raise typer.Exit(ATTENTION)


@logicapp_app.command("params")
def params(
    files: FilesArgument,
    supplied: SuppliedOption = None,
    unsatisfied: Annotated[
        bool, typer.Option("--unsatisfied", help="Only the parameters that will fail.")
    ] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Whether each declared parameter will have a value at deploy time, and from where."""
    statuses = [
        status
        for document in _documents(files)
        for status in parameter_status(document, supplied or ())
        if not (unsatisfied and status.satisfied)
    ]
    render.emit(
        output,
        ["WORKFLOW", "PARAMETER", "TYPE", "SATISFIED", "BY", "REASON"],
        [
            [
                status.workflow or status.source,
                status.name,
                status.type or "",
                ("yes", "green") if status.satisfied else ("no", "red"),
                status.satisfied_by,
                status.reason,
            ]
            for status in statuses
        ],
        [_record(status) for status in statuses],
    )


@logicapp_app.command("references")
def references(
    files: FilesArgument,
    unwired: Annotated[
        bool, typer.Option("--unwired", help="Only keys the wrapper does not wire.")
    ] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """The $connections keys each definition uses, where, and whether each is wired.

    A key the definition uses but nobody wired saves and deploys, then fails when the
    workflow runs. Exits 3 when any key is unwired. A bare definition carries no values,
    so its keys show as unknown.
    """
    found = [
        reference
        for document in _documents(files)
        for reference in connection_references(document)
        if not (unwired and reference.wired is not False)
    ]
    render.emit(
        output,
        ["WORKFLOW", "KEY", "USED BY", "WIRED"],
        [
            [
                reference.workflow or reference.source,
                reference.key,
                ", ".join(reference.used_by),
                "?"
                if reference.wired is None
                else ("yes", "green")
                if reference.wired
                else ("no", "red"),
            ]
            for reference in found
        ],
        [_record(reference) for reference in found],
    )
    if any(reference.wired is False for reference in found):
        raise typer.Exit(ATTENTION)


@logicapp_app.command("connections")
def connections(files: FilesArgument, output: OutputOption = Output.TABLE) -> None:
    """The managed API connections each export resolves, and whether they use managed identity."""
    found = [
        connection for document in _documents(files) for connection in connections_of(document)
    ]
    render.emit(
        output,
        ["WORKFLOW", "KEY", "CONNECTION", "AUTHENTICATION", "MANAGED IDENTITY", "CONNECTION ID"],
        [
            [
                connection.workflow or connection.source,
                connection.key,
                connection.connection_name,
                connection.authentication or "",
                render.yes_no(connection.managed_identity),
                connection.connection_id or "",
            ]
            for connection in found
        ],
        [
            {**_record(connection), "managed_identity": connection.managed_identity}
            for connection in found
        ],
    )


@logicapp_app.command("order")
def order(files: FilesArgument, output: OutputOption = Output.TABLE) -> None:
    """The order a set of workflows must deploy in: tier 0 first.

    A workflow that dispatches to a sibling (a native Workflow action) deploys after it,
    since Azure checks the target when the caller is written.
    """
    steps = deploy_order(_documents(files))
    render.emit(
        output,
        ["TIER", "WORKFLOW", "DEPENDS ON"],
        [[str(step.tier), step.workflow, ", ".join(step.depends_on)] for step in steps],
        [_record(step) for step in steps],
    )


@logicapp_app.command("diff")
def diff(
    reference: Annotated[Path, typer.Argument(help="The baseline, e.g. the rendered template.")],
    difference: Annotated[Path, typer.Argument(help="The other, e.g. the deployed export.")],
    parameters: Annotated[
        bool, typer.Option("--parameters", help="Compare the wrapper parameter values too.")
    ] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Compare two definitions, whatever their shapes, and list where they differ.

    Exits 3 when they differ.
    """
    found = compare(load(reference), load(difference), parameter_values=parameters)
    render.emit(
        output,
        ["PATH", "CHANGE", "REFERENCE", "DIFFERENCE"],
        [
            [item.path, item.change, _short(item.reference), _short(item.difference)]
            for item in found
        ],
        [_record(item) for item in found],
    )
    render.note(f"{len(found)} difference(s)")
    if found:
        raise typer.Exit(ATTENTION)


@logicapp_app.command("defaults")
def defaults(
    file: Annotated[Path, typer.Argument(help="An export (code view or ARM shape).")],
    force: Annotated[
        bool, typer.Option("--force", help="Replace defaults that are already there.")
    ] = False,
    out: OutFileOption = None,
) -> None:
    """Copy each wrapper value onto its declaration as a default, so the definition stands alone.

    $connections and secure parameters are left alone. The result carries the source
    estate's values; rewrite re-points them.
    """
    definition, added = with_parameter_defaults(load(file), force=force)
    _write(json.dumps(definition, indent=2) + "\n", out)
    render.note(f"added {added} default(s)")


@logicapp_app.command("rewrite")
def rewrite(
    file: Annotated[Path, typer.Argument(help="The definition to re-point.")],
    replace: Annotated[
        list[str],
        typer.Option(
            "--replace",
            help="OLD=NEW, a literal find and replace. Repeatable; applied in order.",
            show_default=False,
        ),
    ],
    out: OutFileOption = None,
) -> None:
    """Rewrite estate-specific references (ids, names, URLs) to lift a definition elsewhere.

    Replacements are literal and applied in the order given, most specific first.
    """
    pairs = []
    for item in replace:
        old, separator, new = item.partition("=")
        if not separator or not old:
            raise typer.BadParameter(f"--replace takes OLD=NEW, not {item!r}")
        pairs.append((old, new))
    _write(rewrite_references(load(file).text, pairs), out)


@logicapp_app.command("export")
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
        [[row["workflow"], row["path"]] for row in rows],
        rows,
    )
    render.note(f"exported {len(rows)} workflow(s) to {out}")


@logicapp_app.command("validate")
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
        _record(verdict),
    )
    if not verdict.valid:
        raise typer.Exit(ATTENTION)


# Shared -------------------------------------------------------------------------------


def _documents(paths: list[Path]) -> list[WorkflowDocument]:
    """Every definition named, folders expanded to their .json and .json.tftpl files."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.iterdir()
                    if item.is_file() and item.name.endswith((".json", ".json.tftpl"))
                )
            )
        else:
            files.append(path)
    if not files:
        raise InputError("no definition files found", hint="pass .json or .json.tftpl files")
    return [load(file) for file in files]


def _subscription(runtime, profile: Profile, given: str | None) -> str:
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


def _record(item: object) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(item)  # type: ignore[call-overload]


def _short(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _write(text: str, out: Path | None) -> None:
    if out is None:
        typer.echo(text, nl=not text.endswith("\n"))
        return
    out.write_text(text, encoding="utf-8")
    render.note(f"wrote {out}")
