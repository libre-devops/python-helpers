import zipfile

import pytest

from fakes.analyzer import (
    LINUX_CATALOGUE,
    LINUX_XML,
    MACOS_XML,
    WINDOWS_XML,
    write_linux_zip,
    write_windows_zip,
)
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.analyzer import parse, plain, read_report, reader


def test_a_windows_zip_gives_the_device_its_facts_and_its_findings_errors_first(tmp_path):
    report = read_report(write_windows_zip(tmp_path))
    assert (report.platform, report.host, report.source) == (
        "windows",
        "web01",
        "MDEClientAnalyzerResult.zip",
    )
    assert (report.analyzer_version, report.run_at) == ("01Jul2026", "09/27/2026 00:29:59")
    sections = {fact.section for fact in report.facts}
    assert sections == {"General", "Device", "EDR", "Antivirus"}
    sense = next(fact for fact in report.facts if fact.name == "Sense service Status")
    assert (sense.value, sense.alert) == ("Stopped", "High")
    assert "PowerShell Language mode" in [fact.name for fact in report.facts]  # no ": "
    assert [finding.severity for finding in report.findings] == [
        "error",
        "warning",
        "informational",
    ]
    warning = report.findings[1]
    assert (warning.id, warning.category, warning.check) == (
        "121012",
        "Configuration",
        "SecurityIntelligenceVersion",
    )
    assert warning.result == "Outdated version"
    assert warning.guidance == "Update it:\nUpdates (https://learn.microsoft.com/x) & more"


def test_a_linux_zip_is_described_by_its_own_catalogue_where_it_has_one(tmp_path):
    report = read_report(write_linux_zip(tmp_path))
    assert (report.platform, report.host, report.analyzer_version) == (
        "linux",
        "db01.corp.example",
        "1.5.0",
    )
    by_id = {finding.id: finding for finding in report.findings}
    assert [finding.id for finding in report.findings][:2] == ["332009", "331004"]
    assert (by_id["332009"].severity, by_id["332009"].check, by_id["332009"].result) == (
        "error",
        "Antivirus cloud",
        "the test connections failed",
    )
    assert by_id["331004"].check == "EDR Cloud Cyber"
    assert (
        by_id["331004"].guidance == "Some test connections failed:\nhttps://learn.microsoft.com/y"
    )
    assert (by_id["330002"].severity, by_id["330002"].guidance) == ("informational", "")
    assert by_id["339999"].check == "check 339999"


def test_without_its_catalogue_a_linux_finding_has_this_tools_description(tmp_path):
    report = read_report(write_linux_zip(tmp_path, catalogue=False))
    warning = next(finding for finding in report.findings if finding.id == "331004")
    assert warning.check == "EDR cloud (cyber data)"
    assert "linux-support-connectivity" in warning.guidance


def test_a_mac_is_a_mac(tmp_path):
    assert read_report(write_linux_zip(tmp_path, xml=MACOS_XML)).platform == "macos"


def test_an_unpacked_folder_or_the_xml_itself_reads_the_same(tmp_path):
    windows = tmp_path / "MDEClientAnalyzerResult" / "SystemInfoLogs"
    windows.mkdir(parents=True)
    (windows / "MDEClientAnalyzer.xml").write_text(WINDOWS_XML, encoding="utf-8")
    assert read_report(tmp_path / "MDEClientAnalyzerResult").host == "web01"
    assert read_report(windows / "MDEClientAnalyzer.xml").platform == "windows"
    linux = tmp_path / "mde_support"
    linux.mkdir()
    (linux / "mde.xml").write_text(LINUX_XML, encoding="utf-8")
    (linux / "events.xml").write_text(LINUX_CATALOGUE, encoding="utf-8")
    found = read_report(linux)
    assert next(f for f in found.findings if f.id == "331004").check == "EDR Cloud Cyber"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(InputError, match="holds no MDE Client Analyzer result"):
        read_report(empty)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b'<!DOCTYPE x [<!ENTITY a "b">]><MDEResults/>', "declares a document type"),
        (b"<MDEResults><events>", "cannot be read as XML"),
        (b"<report/>", "not an MDE Client Analyzer result"),
    ],
    ids=["doctype", "broken", "other-xml"],
)
def test_xml_that_is_not_an_analyzer_result_is_refused(data, message):
    with pytest.raises(InputError, match=message):
        parse(data, "result.xml")


def test_a_linux_catalogue_that_declares_a_document_type_is_ignored():
    report = parse(
        LINUX_XML.encode(), "mde.xml", b'<!DOCTYPE x><events><event id="331004"/></events>'
    )
    assert next(f for f in report.findings if f.id == "331004").check == "EDR cloud (cyber data)"


def test_a_zip_without_a_result_or_a_result_past_the_cap_is_refused(tmp_path, monkeypatch):
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("notes.txt", "nothing here")
    with pytest.raises(InputError, match="holds no MDE Client Analyzer result"):
        read_report(other)
    monkeypatch.setattr(reader, "MAX_XML_BYTES", 100)
    with pytest.raises(InputError, match="larger than"):
        read_report(write_windows_zip(tmp_path))
    big = tmp_path / "big.xml"
    big.write_text(WINDOWS_XML, encoding="utf-8")
    with pytest.raises(InputError, match="larger than"):
        read_report(big)


def test_html_snippets_become_text_with_their_links():
    text = (
        "See <a target='_blank' href=\"https://a.example/x\">the <b>docs</b></a>"
        "<br/>then &lt;retry&gt;"
    )
    assert plain(text) == "See the docs (https://a.example/x)\nthen <retry>"
    assert plain("  a  \n\n  b  ") == "a\nb"
