"""The offline Logic App commands: they read definitions from files, and nothing else."""

import dataclasses
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    SortOption,
    UniqueOption,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import InputError
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


def register(app: typer.Typer) -> None:
    """Add the offline commands to ``app``: ``check``, ``params``, ``references``,
    ``connections``, ``order``, ``diff``, ``defaults`` and ``rewrite``."""
    app.command("check")(check_command)
    app.command("params")(params)
    app.command("references")(references)
    app.command("connections")(connections)
    app.command("order")(order)
    app.command("diff")(diff)
    app.command("defaults")(defaults)
    app.command("rewrite")(rewrite)


_SEVERITY_COLOURS = {"error": "red", "warning": "yellow"}

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

OutFileOption = Annotated[
    Path | None,
    typer.Option(
        "--out", help="Write here instead of printing.", dir_okay=False, show_default=False
    ),
]


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
    sort: SortOption = None,
    unique: UniqueOption = None,
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
        [record(finding) for finding in findings],
    )
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = len(findings) - errors
    render.note(f"{len(documents)} definition(s): {errors} error(s), {warnings} warning(s)")
    if errors or (strict and warnings):
        raise typer.Exit(ATTENTION)


def params(
    files: FilesArgument,
    supplied: SuppliedOption = None,
    unsatisfied: Annotated[
        bool, typer.Option("--unsatisfied", help="Only the parameters that will fail.")
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
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
        [record(status) for status in statuses],
    )


def references(
    files: FilesArgument,
    unwired: Annotated[
        bool, typer.Option("--unwired", help="Only keys the wrapper does not wire.")
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
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
        [record(reference) for reference in found],
    )
    if any(reference.wired is False for reference in found):
        raise typer.Exit(ATTENTION)


def connections(
    files: FilesArgument,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
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
            {**record(connection), "managed_identity": connection.managed_identity}
            for connection in found
        ],
    )


def order(
    files: FilesArgument,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The order a set of workflows must deploy in: tier 0 first.

    A workflow that dispatches to a sibling (a native Workflow action) deploys after it,
    since Azure checks the target when the caller is written.
    """
    steps = deploy_order(_documents(files))
    render.emit(
        output,
        ["TIER", "WORKFLOW", "DEPENDS ON"],
        [[str(step.tier), step.workflow, ", ".join(step.depends_on)] for step in steps],
        [record(step) for step in steps],
    )


def diff(
    reference: Annotated[Path, typer.Argument(help="The baseline, e.g. the rendered template.")],
    difference: Annotated[Path, typer.Argument(help="The other, e.g. the deployed export.")],
    parameters: Annotated[
        bool, typer.Option("--parameters", help="Compare the wrapper parameter values too.")
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
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
        [record(item) for item in found],
    )
    render.note(f"{len(found)} difference(s)")
    if found:
        raise typer.Exit(ATTENTION)


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


def record(item: Any) -> dict[str, Any]:
    """A finding or status (a dataclass) as JSON."""
    return dataclasses.asdict(item)


def _short(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _write(text: str, out: Path | None) -> None:
    if out is None:
        typer.echo(text, nl=not text.endswith("\n"))
        return
    out.write_text(text, encoding="utf-8")
    render.note(f"wrote {out}")
