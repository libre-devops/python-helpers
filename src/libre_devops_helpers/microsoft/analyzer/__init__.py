"""MDE Client Analyzer results: each device's facts and findings, read from the result
zip Microsoft's analyzer writes on Windows, Linux or macOS.

Reads local files only: nothing is sent anywhere, so it needs no sign-in. Depends only
on ``core`` and the shared Microsoft layer. Public API::

    from libre_devops_helpers.microsoft.analyzer import read_report

    report = read_report(Path("MDEClientAnalyzerResult.zip"))
    for finding in report.findings:  # errors first, then warnings
        print(report.host, finding.severity, finding.check, finding.result)
"""

from libre_devops_helpers.microsoft.analyzer.models import (
    SEVERITIES,
    AnalyzerReport,
    Fact,
    Finding,
    Platform,
)
from libre_devops_helpers.microsoft.analyzer.reader import MAX_XML_BYTES, parse, plain, read_report
from libre_devops_helpers.microsoft.resources import Requirement

# Nothing: the results are local files.
REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "MAX_XML_BYTES",
    "REQUIREMENTS",
    "SEVERITIES",
    "AnalyzerReport",
    "Fact",
    "Finding",
    "Platform",
    "parse",
    "plain",
    "read_report",
]
