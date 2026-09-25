from datetime import UTC, datetime

from fakes.detections import legacy_rule, rule
from libre_devops_helpers.microsoft.detections import DetectionRule


def test_a_rule_reads_the_current_shape():
    found = DetectionRule.from_json(rule())
    assert (found.id, found.display_name, found.status) == (
        "7506",
        "Certutil used to download remote content",
        "enabled",
    )
    assert (found.frequency, found.schedule) == ("PT3H", "every 3h")
    assert found.next_run == datetime(2026, 9, 25, 12, tzinfo=UTC)
    assert (found.title, found.severity) == ("Certutil download", "medium")
    assert found.tactics == ("CommandAndControl",)
    assert found.techniques == ("T1105", "T1059", "T1059.001")
    assert found.query.startswith("DeviceProcessEvents")
    assert (found.modified_by, found.modified) == (
        "ana@example.com",
        datetime(2026, 9, 20, 9, tzinfo=UTC),
    )
    assert not found.auto_disabled


def test_a_rule_defender_turned_off_says_so():
    assert DetectionRule.from_json(rule(status="autoDisabled")).auto_disabled
    assert DetectionRule.from_json(rule(schedule={"frequency": "PT0S"})).schedule == "continuous"


def test_a_legacy_rule_falls_back_to_what_it_has():
    found = DetectionRule.from_json(legacy_rule())
    assert (found.status, found.frequency, found.schedule) == ("disabled", "PT12H", "every 12h")
    assert (found.tactics, found.techniques) == (("Execution",), ("T1059",))
    empty = DetectionRule.from_json({})
    assert (empty.status, empty.frequency, empty.schedule, empty.tactics) == ("", "", "-", ())
