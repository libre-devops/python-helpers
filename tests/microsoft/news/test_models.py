from datetime import UTC, datetime

from fakes.planner import message
from libre_devops_helpers.microsoft.news import MESSAGE_KEY, Message


def test_a_post_reads_every_field_and_says_where_it_is():
    found = Message.from_json(
        message("MC1000003", "Sentinel", severity="high", action_by="2026-10-01T00:00:00Z")
    )
    assert found.url == "https://admin.microsoft.com/#/MessageCenter/:/messages/MC1000003"
    assert found.category_label == "plan for change"
    assert found.action_by == datetime(2026, 10, 1, tzinfo=UTC)
    assert found.task_title == "MC1000003: Sentinel"
    assert found.for_any(["defender"])
    assert not found.for_any(["teams"])
    assert MESSAGE_KEY.search("mc1000003: anything").group(1) == "mc1000003"
    assert MESSAGE_KEY.search("[Microsoft Sentinel] Sentinel [MC1000003]").group(1) == "MC1000003"
    assert MESSAGE_KEY.search("Before MC1000003 is read") is None
    bare = Message.from_json({"id": "MC1"})
    assert (bare.services, bare.major, bare.body_html, bare.category_label) == ((), False, "", "")
