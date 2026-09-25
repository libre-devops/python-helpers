"""Defender XDR custom detection rules: list them, show one, and export them as YAML.

Custom detection rules are where detections live in the Defender portal, Sentinel's
included once it runs there. The export writes the analyst YAML layout of the Terraform
module terraform-msgraph-xdr-custom-detection-rules, so hand-made rules can be brought
under code.
"""

from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand
from libre_devops_helpers.microsoft.detections import (
    STATUSES,
    DetectionRule,
    Written,
    export_rule,
    export_rules,
    write_rules,
)

detections_app = typer.Typer(
    rich_markup_mode="markdown",
    name="detections",
    help="Custom detection rules: list them, show one, export them as YAML for Terraform.",
    no_args_is_help=True,
)
_STATUS_COLOURS = {"enabled": "green", "disabled": "yellow", "autodisabled": "red"}
_SEVERITIES = ("informational", "low", "medium", "high")
_EXPORTER = brand.command("xdr detections export")


def register(app: typer.Typer) -> None:
    """Add the ``detections`` commands to ``app`` (the ``xdr`` group)."""
    app.add_typer(detections_app)


NoIdOption = Annotated[
    bool,
    typer.Option(
        "--no-id",
        help="Leave the rule's id out, for a backup that creates the rules anew. By default "
        "it is kept, so terraform import and later plans line up.",
    ),
]


@detections_app.command("list")
def list_rules(
    ctx: typer.Context,
    status: Annotated[
        list[str] | None,
        typer.Option("--status", help="Only rules enabled, disabled or autoDisabled. Repeatable."),
    ] = None,
    severity: Annotated[
        list[str] | None,
        typer.Option(
            "--severity", help="Only informational, low, medium or high rules. Repeatable."
        ),
    ] = None,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """The custom detection rules: status, schedule, severity, tactic and who changed them.

    Exits 3 when Defender has turned a rule off itself (autoDisabled), usually after its
    query failed again and again: since 1 October 2026 the API no longer reports how each
    run went, so that is the sign left. Needs CustomDetection.Read.All on the Graph token.
    """
    statuses = _chosen(status, STATUSES, "--status")
    severities = _chosen(severity, _SEVERITIES, "--severity")
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    found = [
        rule
        for rule in runtime.detections(selected).rules()
        if (not statuses or rule.status.casefold() in statuses)
        and (not severities or rule.severity.casefold() in severities)
    ]
    render.emit(
        output,
        ["RULE", "STATUS", "SCHEDULE", "SEVERITY", "TACTIC", "NEXT RUN", "CHANGED", "BY", "ID"],
        [_rule_row(rule) for rule in found],
        [dict(rule.raw) for rule in found],
    )
    off = [rule for rule in found if rule.auto_disabled]
    render.note(f"{_counts(found)} (profile {selected.name})")
    if off:
        render.warn(
            f"Defender turned {len(off)} rule(s) off itself, usually after their queries "
            f"failed: see one with {brand.command('xdr detections show NAME')}"
        )
        raise typer.Exit(ATTENTION)


@detections_app.command("show")
def show(
    ctx: typer.Context,
    rule: Annotated[
        str, typer.Argument(metavar="NAME_OR_ID", help="The rule's display name, or its id.")
    ],
    as_yaml: Annotated[
        bool,
        typer.Option(
            "--yaml",
            help="As the YAML file terraform-msgraph-xdr-custom-detection-rules reads, "
            "as the export writes it.",
        ),
    ] = False,
    no_id: NoIdOption = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """One custom detection rule: its settings and its query, or --yaml as a file for Terraform."""
    runtime = get_runtime(ctx).microsoft
    raw = runtime.detections(runtime.profile(profile)).raw_rule(rule)
    found = DetectionRule.from_json(raw)
    if as_yaml:
        exported = export_rule(raw, keep_id=not no_id, exporter=_EXPORTER)
        render.echo(exported.text.rstrip("\n"))
        for note in exported.notes:
            render.warn(f"review: {note}")
        return
    if output is not Output.TABLE:
        render.emit(
            output, ["RULE", "STATUS", "SCHEDULE", "SEVERITY", "ID"], [_short_row(found)], raw
        )
        return
    render.echo(render.pairs(_rule_pairs(found)))
    render.echo()
    render.echo(render.title("Query"))
    render.echo(found.query or "-")


@detections_app.command("export")
def export(
    ctx: typer.Context,
    folder: Annotated[
        Path,
        typer.Argument(
            help="The folder to write into: one file per rule, in a folder for its tactic.",
            file_okay=False,
        ),
    ],
    names: Annotated[
        list[str] | None,
        typer.Option("--name", help="Only this rule, by display name or id. Repeatable."),
    ] = None,
    no_id: NoIdOption = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite files that are there already.")
    ] = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Export custom detection rules as YAML, for terraform-msgraph-xdr-custom-detection-rules.

    One file per rule at TACTIC/RULE-NAME.yaml, in the layout and schema the module reads.
    The rule's id is kept, so terraform import lines up
    (--no-id for a backup that creates the rules anew). What needs review is a
    TODO(export) comment in the file. Files already there are kept unless --force. Only
    reads the tenant.
    """
    runtime = get_runtime(ctx).microsoft
    detections = runtime.detections(runtime.profile(profile))
    raw = [detections.raw_rule(name) for name in names] if names else detections.raw_rules()
    exported = export_rules(raw, keep_id=not no_id, exporter=_EXPORTER)
    results = write_rules(exported, folder, force=force)
    render.emit(
        output,
        ["RULE", "FILE", "RESULT", "TO REVIEW"],
        [_written_row(item) for item in results],
        [_written_record(item) for item in results],
    )
    _export_notes(results, folder)


def _chosen(values: list[str] | None, known: Any, option: str) -> set[str]:
    """The values given, folded (``auto-disabled`` is ``autodisabled``); a usage error for one
    that is not in ``known``."""
    chosen = {value.casefold().replace("-", "") for value in values or ()}
    unknown = sorted(chosen - set(known))
    if unknown:
        raise typer.BadParameter(f"{', '.join(unknown)}: use {', '.join(known)}", param_hint=option)
    return chosen


def _counts(rules: list[DetectionRule]) -> str:
    counts: dict[str, int] = {}
    for rule in rules:
        label = STATUSES.get(rule.status.casefold(), rule.status or "unknown")
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{count} {label}" for label, count in counts.items()]
    return f"{len(rules)} rule(s)" + (f": {', '.join(parts)}" if parts else "")


def _status_cell(rule: DetectionRule) -> render.Cell:
    return (rule.status or "-", _STATUS_COLOURS.get(rule.status.casefold()))


def _rule_row(rule: DetectionRule) -> list[render.Cell]:
    return [
        rule.display_name,
        _status_cell(rule),
        rule.schedule,
        rule.severity,
        rule.tactics[0] if rule.tactics else "",
        render.when(rule.next_run),
        render.when(rule.modified),
        rule.modified_by,
        rule.id,
    ]


def _short_row(rule: DetectionRule) -> list[render.Cell]:
    return [rule.display_name, _status_cell(rule), rule.schedule, rule.severity, rule.id]


def _rule_pairs(rule: DetectionRule) -> list[tuple[str, str]]:
    return [
        ("Rule", rule.display_name),
        ("Id", rule.id),
        ("Status", STATUSES.get(rule.status.casefold(), rule.status)),
        ("Schedule", rule.schedule),
        ("Next run", render.when(rule.next_run)),
        ("Alert", rule.title),
        ("Severity", rule.severity),
        ("Tactics", ", ".join(rule.tactics)),
        ("Techniques", ", ".join(rule.techniques)),
        ("Description", rule.description),
        ("Created", f"{render.when(rule.created)} by {rule.created_by or '-'}"),
        ("Changed", f"{render.when(rule.modified)} by {rule.modified_by or '-'}"),
    ]


def _written_row(item: Written) -> list[render.Cell]:
    colours = {"written": "green", "kept": "yellow", "refused": "red"}
    return [
        item.exported.rule.display_name,
        str(item.target),
        (item.result, colours[item.result]),
        str(len(item.exported.notes) or ""),
    ]


def _written_record(item: Written) -> dict[str, Any]:
    return {
        "rule": item.exported.rule.display_name,
        "id": item.exported.rule.id,
        "file": str(item.target),
        "result": item.result,
        "to_review": list(item.exported.notes),
    }


def _export_notes(results: list[Written], folder: Path) -> None:
    written = sum(1 for item in results if item.result == "written")
    review = sum(1 for item in results if item.result == "written" and item.exported.notes)
    render.note(f"wrote {written} of {len(results)} rule(s) to {folder}")
    if review:
        render.warn(f"{review} file(s) have TODO(export) comments to review before committing")
    kept = sum(1 for item in results if item.result == "kept")
    if kept:
        render.warn(f"kept {kept} file(s) that were there already: --force overwrites them")
    refused = sum(1 for item in results if item.result == "refused")
    if refused:
        render.warn(f"did not write {refused} file(s): a link was in the way")
