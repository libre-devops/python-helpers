import json

import jsonschema
import yaml

from fakes.detections import PATH, SCHEMA, rule
from fakes.http import routes
from fakes.tenant import run, usage_error

RULES = (
    200,
    {
        "value": [
            rule("1", "Certutil download"),
            rule("2", "Failing rule", status="autoDisabled"),
            rule(
                "3",
                "Quiet rule",
                status="disabled",
                detectionAction={"alertTemplate": {"severity": "low"}},
            ),
        ]
    },
)


def test_list_shows_each_rule_and_exits_3_when_defender_turned_one_off(config_file):
    result = run(config_file, routes({PATH: RULES}), ["xdr", "detections", "list", "-o", "csv"])
    assert result.exit_code == 3, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "RULE,STATUS,SCHEDULE,SEVERITY,TACTIC,NEXT RUN,CHANGED,BY,ID"
    assert [line.split(",")[:4] for line in lines[1:]] == [
        ["Certutil download", "enabled", "every 3h", "medium"],
        ["Failing rule", "autoDisabled", "every 3h", "medium"],
        ["Quiet rule", "disabled", "every 3h", "low"],
    ]
    stderr = " ".join(result.stderr.split())
    assert "3 rule(s): 1 enabled, 1 turned off by Defender, 1 disabled" in stderr
    assert "Defender turned 1 rule(s) off itself" in stderr


def test_list_filters_on_status_and_severity(config_file):
    args = ["xdr", "detections", "list", "--status", "enabled", "--status", "disabled"]
    result = run(config_file, routes({PATH: RULES}), [*args, "--severity", "LOW", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert [item["id"] for item in json.loads(result.stdout)] == ["3"]
    bad = run(config_file, routes({}), ["xdr", "detections", "list", "--status", "paused"])
    assert bad.exit_code == 2
    assert "paused: use enabled, disabled, autodisabled" in usage_error(bad)


def test_show_gives_the_settings_and_the_query(config_file):
    handler = routes({f"{PATH}/1": (200, rule("1", "Certutil download"))})
    result = run(config_file, handler, ["xdr", "detections", "show", "1"])
    assert result.exit_code == 0, result.output
    assert "Tactics      CommandAndControl" in result.stdout
    assert "Techniques   T1105, T1059, T1059.001" in result.stdout
    assert result.stdout.rstrip().endswith("| project Timestamp, ReportId, DeviceId, DeviceName")


def test_show_as_yaml_is_a_file_the_terraform_module_accepts(config_file):
    handler = routes({PATH: (200, {"value": [rule("2", "Failing", status="autoDisabled")]})})
    result = run(config_file, handler, ["xdr", "detections", "show", "failing", "--yaml"])
    assert result.exit_code == 0, result.output
    spec = yaml.safe_load(result.stdout)
    jsonschema.validate(spec, SCHEMA)
    assert (spec["id"], spec["status"]) == ("2", "disabled")
    assert "review: Defender turned this rule off itself" in result.stderr
    without = run(
        config_file, handler, ["xdr", "detections", "show", "failing", "--yaml", "--no-id"]
    )
    assert "id" not in yaml.safe_load(without.stdout)


def test_export_writes_the_modules_layout_and_keeps_what_is_there(config_file, tmp_path):
    handler = routes({PATH: RULES})
    folder = tmp_path / "custom-detections"
    first = run(config_file, handler, ["xdr", "detections", "export", str(folder)])
    assert first.exit_code == 0, first.output
    files = sorted(str(path.relative_to(folder)) for path in folder.rglob("*.yaml"))
    assert files == [
        "command-and-control/certutil-download.yaml",
        "command-and-control/failing-rule.yaml",
        "uncategorised/quiet-rule.yaml",
    ]
    # Every file meets the module's schema, or says in a TODO why it cannot yet: the quiet
    # rule maps no entities, and inventing mappings would be worse than asking.
    for path in folder.rglob("*.yaml"):
        text = path.read_text("utf-8")
        valid = jsonschema.Draft7Validator(SCHEMA).is_valid(yaml.safe_load(text))
        assert valid or "# TODO(export): the rule maps no entities" in text, path
    assert "wrote 3 of 3 rule(s)" in first.stderr
    assert "2 file(s) have TODO(export) comments" in first.stderr  # autoDisabled; no mappings
    again = run(config_file, handler, ["xdr", "detections", "export", str(folder), "-o", "json"])
    assert {item["result"] for item in json.loads(again.stdout)} == {"kept"}
    assert "--force overwrites them" in again.stderr
    forced = run(config_file, handler, ["xdr", "detections", "export", str(folder), "--force"])
    assert "wrote 3 of 3 rule(s)" in forced.stderr


def test_export_takes_chosen_rules_and_can_leave_ids_out(config_file, tmp_path):
    handler = routes({f"{PATH}/1": (200, rule("1", "Certutil download"))})
    args = ["xdr", "detections", "export", str(tmp_path), "--name", "1", "--no-id"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    (path,) = tmp_path.rglob("*.yaml")
    assert "id" not in yaml.safe_load(path.read_text("utf-8"))
