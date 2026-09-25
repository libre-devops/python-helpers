import copy
import sys
from datetime import UTC, datetime

import jsonschema
import pytest
import yaml

from fakes.detections import SCHEMA, legacy_rule, rule
from libre_devops_helpers.microsoft.detections import SCHEMA_URL, export_rule, export_rules

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


def exported(data, **options):
    found = export_rule(data, now=NOW, exporter="ldo xdr detections export", **options)
    return found, yaml.safe_load(found.text)


def test_a_rule_becomes_the_modules_yaml_and_meets_its_schema():
    found, spec = exported(rule())
    jsonschema.validate(spec, SCHEMA)
    assert str(found.path) == "command-and-control/certutil-used-to-download-remote-content.yaml"
    assert spec == {
        "id": "7506",
        "display_name": "Certutil used to download remote content",
        "description": "certutil fetching from the internet",
        "status": "enabled",
        "frequency": "PT3H",
        "query": 'DeviceProcessEvents\n| where FileName =~ "certutil.exe"\n'
        "| project Timestamp, ReportId, DeviceId, DeviceName",
        "alert": {
            "title": "Certutil download",
            "description": "certutil fetched remote content",
            "severity": "medium",
            "recommended_actions": "Recover and detonate the downloaded content.",
            "mitre": [
                {
                    "tactic": "CommandAndControl",
                    "techniques": [
                        "T1105",
                        {"technique": "T1059", "sub_techniques": ["T1059.001"]},
                    ],
                }
            ],
            "custom_details": {"CommandLine": "ProcessCommandLine"},
            "entity_mappings": {
                "hosts": [{"device_id_column": "DeviceId", "name_column": "DeviceName"}]
            },
        },
        "device_groups": ["Workstations-Corp"],
    }
    assert found.notes == ()


def test_the_header_names_the_schema_the_exporter_and_why_the_id_is_kept():
    found, _ = exported(rule())
    lines = found.text.splitlines()
    assert lines[0] == f"# yaml-language-server: $schema={SCHEMA_URL}"
    assert lines[2] == (
        "# Exported from Microsoft Defender XDR by ldo xdr detections export on 2026-09-25 10:00Z."
    )
    assert "keys" in lines[3]
    assert "import" in lines[4]
    without, spec = exported(rule(), keep_id=False)
    assert "id" not in spec
    assert "server assigned" not in without.text


def test_a_rule_defender_turned_off_is_exported_disabled_with_why():
    found, spec = exported(rule(status="autoDisabled"))
    jsonschema.validate(spec, SCHEMA)  # the schema allows enabled and disabled only
    assert spec["status"] == "disabled"
    assert found.notes[0].startswith("Defender turned this rule off itself (autoDisabled)")
    assert found.text.count("# TODO(export): Defender turned this rule off itself") == 1


def test_automated_actions_and_oauth_names_take_the_modules_spelling():
    data = rule()
    template = data["detectionAction"]["alertTemplate"]
    template["entityMappings"]["oAuthApplications"] = [{"oAuthAppIdColumn": "AppId"}]
    template["entityMappings"]["mailMessages"] = []  # an empty group is left out
    data["detectionAction"]["automatedActions"] = {
        "@odata.type": "#microsoft.graph.security.automatedActions",
        "isolateDevices": [{"deviceIdColumn": "DeviceId", "isolationType": "full"}],
        "blockFiles": [],
    }
    found, spec = exported(data)
    jsonschema.validate(spec, SCHEMA)
    assert spec["alert"]["entity_mappings"]["oauth_applications"] == [
        {"oauth_app_id_column": "AppId"}
    ]
    assert "mail_messages" not in spec["alert"]["entity_mappings"]
    assert spec["automated_actions"] == {
        "isolate_devices": [{"device_id_column": "DeviceId", "isolation_type": "full"}]
    }
    assert any("allow_automated_actions = true" in note for note in found.notes)


def test_a_legacy_rule_is_converted_where_it_can_be_and_noted_where_not():
    found, spec = exported(legacy_rule())
    assert (spec["status"], spec["frequency"]) == ("disabled", "PT12H")
    assert spec["alert"]["mitre"] == [{"tactic": "Execution", "techniques": ["T1059"]}]
    assert str(found.path) == "execution/old-style-rule.yaml"
    assert [note.split(" ", 2)[1] for note in found.notes] == ["impactedAssets", "responseActions"]
    assert all(line.startswith("# TODO(export): legacy") for line in found.text.splitlines()[6:8])


def test_what_cannot_be_mapped_is_noted_and_never_guessed():
    data = legacy_rule()
    data["schedule"] = {"period": "6H"}
    template = data["detectionAction"]["alertTemplate"]
    template["category"] = "SuspiciousActivity"  # not an ATT&CK tactic
    del template["impactedAssets"]
    found, spec = exported(data)
    assert spec["frequency"] == "PT24H"
    assert "mitre" not in spec["alert"]
    assert str(found.path) == "uncategorised/old-style-rule.yaml"
    notes = " ".join(found.notes)
    assert "legacy schedule period '6H' has no mapping" in notes
    assert "legacy category 'SuspiciousActivity' is not an ATT&CK tactic" in notes
    assert "the rule maps no entities" in notes


def test_a_rules_own_text_can_neither_add_keys_nor_leave_the_folder():
    data = legacy_rule(name="../../etc/passwd\nstatus: enabled")
    data["schedule"] = {"period": "6H\nfrequency: PT0S"}
    found, spec = exported(data)
    assert str(found.path) == "execution/etc-passwd-status-enabled.yaml"
    assert spec["display_name"] == "../../etc/passwd\nstatus: enabled"
    assert (spec["status"], spec["frequency"]) == ("disabled", "PT24H")
    comments = [line for line in found.text.splitlines() if line.startswith("#")]
    assert any("'6H\\nfrequency: PT0S'" in line for line in comments)
    assert not any(line.startswith("frequency: PT0S") for line in found.text.splitlines())


def test_rules_that_would_share_a_file_name_both_survive():
    first, second = rule("1", "Same name"), rule("2", "Same name")
    unnamed = rule("3", "")
    paths = [str(item.path) for item in export_rules([first, second, unnamed], now=NOW)]
    assert paths == [
        "command-and-control/same-name.yaml",
        "command-and-control/same-name-2.yaml",
        "command-and-control/rule-3.yaml",
    ]


@pytest.mark.parametrize("frequency", ["PT0S", "PT1H", "PT12H", "PT24H"])
def test_every_schedule_the_api_allows_survives_the_trip(frequency):
    data = copy.deepcopy(rule())
    data["schedule"]["frequency"] = frequency
    _, spec = exported(data)
    jsonschema.validate(spec, SCHEMA)
    assert spec["frequency"] == frequency


def test_files_are_written_under_the_folder_and_never_through_a_link(tmp_path):
    from libre_devops_helpers.microsoft.detections import write_rules

    folder = tmp_path / "out"
    exported = export_rules([rule("1", "One"), rule("2", "Two")], now=NOW)
    first = write_rules(exported, folder)
    assert [item.result for item in first] == ["written", "written"]
    assert (folder / "command-and-control" / "one.yaml").read_text("utf-8") == exported[0].text
    assert [item.result for item in write_rules(exported, folder)] == ["kept", "kept"]
    assert [item.result for item in write_rules(exported, folder, force=True)] == [
        "written",
        "written",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="making links needs privileges on Windows")
def test_a_link_in_the_way_is_never_written_through(tmp_path):
    from libre_devops_helpers.microsoft.detections import write_rules

    folder = tmp_path / "out"
    exported = export_rules([rule("1", "One")], now=NOW)
    write_rules(exported, folder)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    target = folder / "command-and-control" / "one.yaml"
    target.unlink()
    target.symlink_to(outside / "victim.yaml")
    assert write_rules(exported, folder, force=True)[0].result == "refused"
    assert not (outside / "victim.yaml").exists()
    # A category folder that is a link to somewhere else is refused as well.
    target.unlink()
    (folder / "command-and-control").rmdir()
    (folder / "command-and-control").symlink_to(outside, target_is_directory=True)
    assert write_rules(exported, folder, force=True)[0].result == "refused"
    assert list(outside.iterdir()) == []
    # The folder named is trusted, link or not: it is the one asked for.
    linked = tmp_path / "linked-out"
    linked.symlink_to(outside, target_is_directory=True)
    assert write_rules(exported, linked)[0].result == "written"
