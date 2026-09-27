"""``xdr analyzer``: what MDE Client Analyzer results found, device by device."""

from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import OutputOption, SortOption, UniqueOption
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.analyzer import SEVERITIES, AnalyzerReport, Finding, read_report

_COLOURS = {"error": "red", "warning": "yellow"}


def register(app: typer.Typer) -> None:
    """Add ``analyzer`` to ``app``."""
    app.command("analyzer")(analyzer)


def analyzer(
    files: Annotated[
        list[Path],
        typer.Argument(
            metavar="RESULT...",
            help="The analyzer's result zip, the folder it unpacks to, or its XML. Several.",
            exists=True,
        ),
    ],
    severity: Annotated[
        str | None,
        typer.Option("--severity", help="Only findings at least this bad: error or warning."),
    ] = None,
    guidance: Annotated[
        bool, typer.Option("--guidance", help="Add each finding's guidance: what to do.")
    ] = False,
    facts: Annotated[
        bool,
        typer.Option("--facts", help="Each device's facts instead: OS, versions, services."),
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """What MDE Client Analyzer results found: each device's findings, errors first.

    Reads the zip the analyzer writes (MDEClientAnalyzerResult.zip on Windows, the support
    tool's zip on Linux and macOS), the folder it unpacks to, or the results XML itself.
    Everything is read here: nothing is sent anywhere. Exits 3 when a device has an
    error or a warning.
    """
    worst = _severity_limit(severity)
    reports = [read_report(path) for path in files]
    records = [_record(report, worst) for report in reports]
    if facts:
        headers = ["HOST", "SECTION", "FACT", "VALUE", "ALERT"]
        rows = [_fact_row(report.host, fact) for report in reports for fact in report.facts]
    else:
        headers = ["HOST", "SEVERITY", "CATEGORY", "CHECK", "RESULT"] + (
            ["GUIDANCE"] if guidance else []
        )
        rows = [
            _finding_row(report.host, finding, guidance=guidance)
            for report in reports
            for finding in _kept(report, worst)
        ]
    render.emit(output, headers, rows, records)
    for report in reports:
        render.note(_summary(report))
    if any(report.count("error") or report.count("warning") for report in reports):
        raise typer.Exit(ATTENTION)


def _severity_limit(severity: str | None) -> int:
    """How many of ``SEVERITIES`` to keep: all of them unless ``--severity`` says."""
    if severity is None:
        return len(SEVERITIES)
    wanted = severity.strip().casefold()
    if wanted not in SEVERITIES:
        raise InputError(
            f"{severity!r} is not a severity", hint="use error, warning or informational"
        )
    return SEVERITIES.index(wanted) + 1


def _kept(report: AnalyzerReport, worst: int) -> list[Finding]:
    return [finding for finding in report.findings if finding.rank < worst]


def _finding_row(host: str, finding: Finding, *, guidance: bool) -> list[render.Cell]:
    cells: list[render.Cell] = [
        host,
        (finding.severity, _COLOURS.get(finding.severity)),
        finding.category,
        finding.check,
        _one_line(finding.result),
    ]
    return cells + ([_one_line(finding.guidance)] if guidance else [])


def _one_line(text: str) -> str:
    # A table row is one line; JSON keeps the analyzer's own line breaks.
    return " ".join(text.split())


def _fact_row(host: str, fact: Any) -> list[render.Cell]:
    alert: render.Cell = (fact.alert, "red") if fact.alert.casefold() == "high" else fact.alert
    return [host, fact.section, fact.name, fact.value, alert]


_PLURALS = {"error": "errors", "warning": "warnings", "informational": "informational"}


def _summary(report: AnalyzerReport) -> str:
    counts = ", ".join(
        f"{report.count(level)} {level if report.count(level) == 1 else _PLURALS[level]}"
        for level in SEVERITIES
    )
    return f"{report.host or 'unknown host'} ({report.platform}, {report.source}): {counts}"


def _record(report: AnalyzerReport, worst: int) -> dict[str, Any]:
    return {
        "source": report.source,
        "platform": report.platform,
        "host": report.host or None,
        "analyzer_version": report.analyzer_version or None,
        "run_at": report.run_at or None,
        "errors": report.count("error"),
        "warnings": report.count("warning"),
        "informational": report.count("informational"),
        "facts": [
            {"section": f.section, "name": f.name, "value": f.value, "alert": f.alert or None}
            for f in report.facts
        ],
        "findings": [
            {
                "id": finding.id,
                "severity": finding.severity,
                "category": finding.category,
                "check": finding.check,
                "result": finding.result,
                "guidance": finding.guidance or None,
            }
            for finding in _kept(report, worst)
        ],
    }
