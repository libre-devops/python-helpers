"""Read an MDE Client Analyzer result: the zip it writes, its unpacked folder, or the XML.

Windows' analyzer writes ``SystemInfoLogs\\MDEClientAnalyzer.xml`` (root ``MDEResults``),
Linux's and macOS's ``mde.xml`` (root ``mdatp``), beside everything else they collect.
Only that one file is read, in memory, however large the zip: nothing is unpacked, so no
name inside it can reach the disk, and a file past ``MAX_XML_BYTES`` is refused rather
than read. XML that declares a document type is refused too: the analyzers never write
one, and it is where entity expansion attacks start.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.analyzer.catalogue import GUIDANCE, describe
from libre_devops_helpers.microsoft.analyzer.models import AnalyzerReport, Fact, Finding, Platform

MAX_XML_BYTES = 16 * 1024 * 1024
WINDOWS_RESULT = "systeminfologs/mdeclientanalyzer.xml"
UNIX_RESULT = "mde.xml"
UNIX_CATALOGUE = "events.xml"
# Windows' sections of device facts, as the analyzer names them, and as they are shown.
WINDOWS_SECTIONS = {
    "general": "General",
    "devInfo": "Device",
    "EDRCompInfo": "EDR",
    "MDEDevConfig": "Configuration",
    "AVCompInfo": "Antivirus",
}
_SEVERITY_WORDS = {"informational": "informational", "warning": "warning", "error": "error"}
_LINK = re.compile(r"<a\b[^>]*?href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def read_report(path: Path) -> AnalyzerReport:
    """The analyzer result at ``path``: a zip, the folder it unpacks to, or its XML."""
    if path.is_dir():
        return _from_folder(path)
    if zipfile.is_zipfile(path):
        return _from_zip(path)
    return parse(_capped(path.read_bytes(), path.name), path.name)


def parse(data: bytes, source: str, catalogue: bytes | None = None) -> AnalyzerReport:
    """A report from the results XML itself; ``catalogue`` is Linux's ``events.xml``, when
    the result carries one, for the checks' own names and guidance."""
    root = _xml(data, source)
    if root.tag == "MDEResults":
        return _windows(root, source)
    if root.tag == "mdatp":
        return _unix(root, source, _catalogue(catalogue, source))
    raise InputError(
        f"{source}: not an MDE Client Analyzer result (its XML is <{root.tag}>)",
        hint="give the result zip, its folder, or MDEClientAnalyzer.xml or mde.xml",
    )


def plain(text: str) -> str:
    """The analyzer's HTML snippets as text: a link as ``words (url)``, markup dropped."""
    text = _LINK.sub(
        lambda match: f"{_TAG.sub('', match.group(2)).strip()} ({match.group(1)})", text
    )
    text = _TAG.sub("", _BREAK.sub("\n", text))
    lines = (" ".join(line.split()) for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


# Finding the results -----------------------------------------------------------------------


def _from_zip(path: Path) -> AnalyzerReport:
    with zipfile.ZipFile(path) as archive:
        # Windows' zips name their files with backslashes.
        members = {info.filename.replace("\\", "/").casefold(): info for info in archive.infolist()}
        windows = _member(members, WINDOWS_RESULT)
        if windows is not None:
            return parse(_read_member(archive, windows, path.name), path.name)
        unix = _member(members, UNIX_RESULT)
        if unix is None:
            raise InputError(
                f"{path.name} holds no MDE Client Analyzer result",
                hint="it should hold SystemInfoLogs\\MDEClientAnalyzer.xml (Windows) or "
                "mde.xml (Linux, macOS)",
            )
        catalogue = _member(members, UNIX_CATALOGUE)
        events = _read_member(archive, catalogue, path.name) if catalogue is not None else None
        return parse(_read_member(archive, unix, path.name), path.name, events)


def _member(members: dict[str, zipfile.ZipInfo], wanted: str) -> zipfile.ZipInfo | None:
    for name, info in members.items():
        if name == wanted or name.endswith("/" + wanted):
            return info
    return None


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, source: str) -> bytes:
    # Read one byte past the cap rather than trust the size the zip's header gives.
    with archive.open(info) as handle:
        return _capped(handle.read(MAX_XML_BYTES + 1), source)


def _from_folder(folder: Path) -> AnalyzerReport:
    for pattern in ("MDEClientAnalyzer.xml", UNIX_RESULT):
        found = sorted(folder.rglob(pattern))
        if found:
            catalogue = sorted(folder.rglob(UNIX_CATALOGUE)) if pattern == UNIX_RESULT else []
            events = _capped(catalogue[0].read_bytes(), str(folder)) if catalogue else None
            return parse(_capped(found[0].read_bytes(), str(folder)), folder.name, events)
    raise InputError(f"{folder} holds no MDE Client Analyzer result")


def _capped(data: bytes, source: str) -> bytes:
    if len(data) > MAX_XML_BYTES:
        raise InputError(f"{source}: the result is larger than {MAX_XML_BYTES // 2**20} MB")
    return data


def _declares_a_type(data: bytes) -> bool:
    return b"<!DOCTYPE" in data or b"<!ENTITY" in data


def _xml(data: bytes, source: str) -> ElementTree.Element:
    """``data`` parsed, refused when it declares a document type."""
    if _declares_a_type(data):
        raise InputError(f"{source}: refusing XML that declares a document type")
    try:
        # S314 would have defusedxml, a dependency this does not need: with no document
        # type, no entity can be declared to expand, and ElementTree fetches nothing.
        return ElementTree.fromstring(data)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise InputError(f"{source}: cannot be read as XML ({exc})") from None


# Windows -------------------------------------------------------------------------------------


def _windows(root: ElementTree.Element, source: str) -> AnalyzerReport:
    facts: list[Fact] = []
    for section in root:
        if section.tag != "events":
            facts.extend(_windows_facts(section))
    findings = [_windows_finding(event) for event in root.iterfind("events/event")]
    report = AnalyzerReport(source, "windows", "", tuple(facts), _worst_first(findings))
    return _identified(report, host="Device Host Name", version="Script Version")


def _windows_facts(section: ElementTree.Element) -> Iterable[Fact]:
    label = WINDOWS_SECTIONS.get(section.tag, section.tag)
    for item in section:
        name = (item.get("displayName") or item.tag).strip().rstrip(":").strip()
        yield Fact(label, name, _text(item.findtext("value")), _text(item.findtext("alert")))


def _windows_finding(event: ElementTree.Element) -> Finding:
    severity = _text(event.findtext("severity")).casefold()
    return Finding(
        id=event.get("id", ""),
        severity=_SEVERITY_WORDS.get(severity, severity or "informational"),
        category=_text(event.findtext("category")),
        check=_text(event.findtext("check")),
        result=plain(_text(event.findtext("checkresult"))),
        guidance=plain(_text(event.findtext("guidance"))),
    )


# Linux and macOS -----------------------------------------------------------------------------


def _unix(
    root: ElementTree.Element, source: str, catalogue: dict[str, tuple[str, str]]
) -> AnalyzerReport:
    facts = [*_unix_facts(root.find("general"), "General")]
    facts += _unix_facts(root.find("device_info"), "Device")
    ids = [event.get("id", "") for event in root.iterfind("events/event")]
    family = next((fact.value for fact in facts if fact.name == "OS Family"), "")
    platform: Platform = "macos" if family == "Darwin" else "linux"
    findings = [_unix_finding(finding_id, platform, catalogue) for finding_id in ids]
    report = AnalyzerReport(source, platform, "", tuple(facts), _worst_first(findings))
    return _identified(report, host="Host Name", version="Script Version")


def _unix_facts(section: ElementTree.Element | None, label: str) -> Iterable[Fact]:
    for item in section if section is not None else ():
        name = item.get("display_name") or item.tag.replace("_", " ").capitalize()
        yield Fact(label, name, _text(item.text))


def _unix_finding(finding_id: str, platform: str, catalogue: dict[str, tuple[str, str]]) -> Finding:
    _, severity, category, check, result = describe(finding_id)
    named, guidance = catalogue.get(finding_id, ("", ""))
    if not guidance and severity != "informational":
        guidance = GUIDANCE.get((platform, category), "")
    return Finding(finding_id, severity, category, named or check, result, guidance)


def _catalogue(data: bytes | None, source: str) -> dict[str, tuple[str, str]]:
    """Linux's own ``events.xml``: each id's check name and guidance."""
    if not data or _declares_a_type(data):
        return {}
    entries: dict[str, tuple[str, str]] = {}
    for event in _xml(data, source).iterfind("event"):
        name, tsg = _text(event.findtext("check_name")), plain(_text(event.findtext("tsg")))
        entries[event.get("id", "")] = (name, tsg)
    return entries


# Shared --------------------------------------------------------------------------------------


def _worst_first(findings: list[Finding]) -> tuple[Finding, ...]:
    # Errors, then warnings, then the rest, each in the order the analyzer wrote them.
    return tuple(sorted(findings, key=lambda finding: finding.rank))


def _identified(report: AnalyzerReport, *, host: str, version: str) -> AnalyzerReport:
    run_at = report.fact("Script RunTime") or report.fact("Script run time")
    return AnalyzerReport(
        source=report.source,
        platform=report.platform,
        host=report.fact(host) or report.fact("Device Name"),
        facts=report.facts,
        findings=report.findings,
        analyzer_version=report.fact(version),
        run_at=run_at,
    )


def _text(value: str | None) -> str:
    return (value or "").strip()
