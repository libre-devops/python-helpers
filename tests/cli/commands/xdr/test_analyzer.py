import json

from fakes.analyzer import write_linux_zip, write_windows_zip
from fakes.http import routes
from fakes.tenant import run
from libre_devops_helpers.core.errors import InputError


def analyzer(config_file, *args):
    # routes({}) answers nothing: the results are read here, and nothing is sent.
    return run(config_file, routes({}), ["xdr", "analyzer", *args])


def test_each_devices_findings_come_errors_first_and_a_warning_exits_3(config_file, tmp_path):
    windows, linux = write_windows_zip(tmp_path), write_linux_zip(tmp_path)
    result = analyzer(config_file, str(windows), str(linux), "-o", "csv")
    assert result.exit_code == 3, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "HOST,SEVERITY,CATEGORY,CHECK,RESULT"
    assert lines[1] == "web01,error,Services,SenseService,Sense is stopped"
    assert lines[2] == "web01,warning,Configuration,SecurityIntelligenceVersion,Outdated version"
    assert lines[4].startswith("db01.corp.example,error,Connectivity,Antivirus cloud,")
    assert "web01 (windows, MDEClientAnalyzerResult.zip): 1 error, 1 warning, 1 informational" in (
        result.stderr
    )
    assert "db01.corp.example (linux, mde_support.zip): 1 error, 1 warning, 2 informational" in (
        result.stderr
    )


def test_severity_keeps_the_worst_and_guidance_says_what_to_do_on_one_line(config_file, tmp_path):
    zipped = str(write_windows_zip(tmp_path))
    result = analyzer(config_file, zipped, "--severity", "warning", "--guidance", "-o", "csv")
    lines = result.stdout.splitlines()
    assert lines[0].endswith(",GUIDANCE")
    assert len(lines) == 3  # the error and the warning
    assert lines[2].endswith(",Update it: Updates (https://learn.microsoft.com/x) & more")
    bad = analyzer(config_file, zipped, "--severity", "bad")
    assert isinstance(bad.exception, InputError)


def test_facts_are_each_devices_versions_and_services(config_file, tmp_path):
    result = analyzer(config_file, str(write_windows_zip(tmp_path)), "--facts", "-o", "csv")
    lines = result.stdout.splitlines()
    assert lines[0] == "HOST,SECTION,FACT,VALUE,ALERT"
    assert "web01,EDR,Sense service Status,Stopped,High" in lines
    assert "web01,Antivirus,Defender AV Security Intelligence Version,1.419.1.0," in lines


def test_json_is_every_report_in_full(config_file, tmp_path):
    result = analyzer(
        config_file, str(write_windows_zip(tmp_path)), "-o", "json", "--severity", "error"
    )
    (report,) = json.loads(result.stdout)
    assert (report["host"], report["platform"], report["errors"], report["warnings"]) == (
        "web01",
        "windows",
        1,
        1,
    )
    assert [finding["id"] for finding in report["findings"]] == ["122001"]
    assert {
        "section": "EDR",
        "name": "Sense service Status",
        "value": "Stopped",
        "alert": "High",
    } in (report["facts"])


def test_results_with_nothing_wrong_exit_0(config_file, tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "mde.xml").write_text(
        "<mdatp><device_info><host_name display_name='Host Name'>db02</host_name></device_info>"
        "<events><event id='330002'/></events></mdatp>",
        encoding="utf-8",
    )
    assert analyzer(config_file, str(clean)).exit_code == 0


def test_html_is_a_page_of_the_findings_with_the_summary(config_file, tmp_path):
    result = analyzer(config_file, str(write_windows_zip(tmp_path)), "-o", "html")
    assert result.exit_code == 3
    assert result.stdout.startswith("<!doctype html>")
    assert '<span class="pill err">error</span>' in result.stdout
    assert "web01 (windows, MDEClientAnalyzerResult.zip): 1 error, 1 warning" in result.stdout
