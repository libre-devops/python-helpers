from datetime import UTC, datetime

from fakes.planner import message
from libre_devops_helpers.microsoft.news import ROLLUP_TITLE, Message, Rollup, listed, months
from libre_devops_helpers.microsoft.news import rollup as module


def post(message_id: str, title: str, **extra) -> Message:
    return Message.from_json(message(message_id, title, **extra))


def test_a_rollup_counts_its_posts_then_lists_them_one_a_line():
    rollup = Rollup(
        "2026-09",
        (
            post(
                "MC1000003",
                "Sentinel: connector\nretired",
                services=("Microsoft Sentinel", "Microsoft Defender XDR"),
                severity="high",
                updated="2026-09-27T23:30:00Z",
            ),
            post("MC1000002", "Teams: meeting recap", services=("Microsoft Teams",)),
            post("MC1000001", "Defender XDR: new hunting tables", category="stayInformed"),
        ),
    )
    assert rollup.title == "Message Center rollup: 2026-09 (3 messages)"
    assert rollup.ids == {"MC1000001", "MC1000002", "MC1000003"}
    assert rollup.description == (
        "# Message Center summary (2026-09)\n"
        "\n"
        "Total: 3 messages (0 critical, 1 high, 2 normal)\n"
        "\n"
        "## By service\n"
        "- Microsoft Defender XDR: 2\n"
        "- Microsoft Sentinel: 1\n"
        "- Microsoft Teams: 1\n"
        "\n"
        "## By category\n"
        "- planForChange: 2\n"
        "- stayInformed: 1\n"
        "\n"
        "## Messages\n"
        "- MC1000003 2026-09-27 [Microsoft Sentinel, Microsoft Defender XDR] Sentinel: "
        "connector retired\n"
        "- MC1000002 2026-09-26 [Microsoft Teams] Teams: meeting recap\n"
        "- MC1000001 2026-09-26 [Microsoft Defender XDR] Defender XDR: new hunting tables"
    )
    assert listed(rollup.description) == rollup.ids


def test_one_post_and_an_unusual_severity_read_plainly():
    bare = Message.from_json({"id": "MC7", "title": "Quiet", "severity": "Advisory"})
    rollup = Rollup("2026-10", (bare,))
    assert rollup.title == "Message Center rollup: 2026-10 (1 message)"
    assert "Total: 1 messages (0 critical, 0 high, 0 normal, 1 advisory)" in rollup.description
    assert rollup.description.endswith("## By category\n- none: 1\n\n## Messages\n- MC7 - Quiet")


def test_a_long_month_is_cut_to_fit_and_says_how_many_are_left_out(monkeypatch):
    monkeypatch.setattr(module, "DESCRIPTION_LIMIT", 600)
    posts = tuple(post(f"MC{n}", f"Post number {n} " + "x" * 40) for n in range(100, 120))
    description = Rollup("2026-09", posts).description
    assert len(description) <= 600
    shown = listed(description)
    assert 0 < len(shown) < 20
    assert description.rsplit("\n", 1)[1] == f"- and {20 - len(shown)} more, too many for one task"


def test_a_rollup_keeps_the_lines_of_posts_it_listed_that_the_month_no_longer_has():
    before = (
        "# Message Center summary (month 2026-07)\n\n## Messages\n"
        "- MC1000001 2026-07-20 [Microsoft Teams] Still here\n"
        "- MC1183010 2026-07-20 [Microsoft Teams] Gone since \n"
        "- MC1409304 (Updated) An older layout\n"
        "- MC1183010 2026-07-20 [Microsoft Teams] Gone since, twice\n"
    )
    rollup = Rollup("2026-07", (post("MC1000001", "Still here"),)).keeping(before)
    assert rollup.earlier == (
        "- MC1183010 2026-07-20 [Microsoft Teams] Gone since",
        "- MC1409304 (Updated) An older layout",
    )
    assert rollup.title == "Message Center rollup: 2026-07 (1 message)"
    assert rollup.description.endswith(
        "- MC1000001 2026-09-26 [Microsoft Defender XDR] Still here\n"
        "\n"
        "## Listed before\n"
        "Listed before, and no longer among the month's posts: changed again since, or gone "
        "from Message Center.\n"
        "- MC1183010 2026-07-20 [Microsoft Teams] Gone since\n"
        "- MC1409304 (Updated) An older layout"
    )
    assert listed(rollup.description) == {"MC1000001", "MC1183010", "MC1409304"}
    assert rollup.keeping(rollup.description) == rollup


def test_listed_reads_this_layout_and_the_one_before_it():
    earlier = "- MC1409304 (Updated) Teams: facilitator\n- MC1325416 Guest invites\n"
    assert listed(earlier) == {"MC1409304", "MC1325416"}
    assert listed("## Messages\n- mc5 2026-09-01 [Teams] x\n- and 3 more") == {"MC5"}
    assert listed("MC9 at the start of a line is not a listed post") == frozenset()


def test_a_rollups_title_names_its_month_in_either_layout():
    assert ROLLUP_TITLE.search("Message Center rollup: 2026-07 (8 messages)").group(1) == "2026-07"
    assert ROLLUP_TITLE.search("Message Center rollup: month 2026-07 (8)").group(1) == "2026-07"
    assert ROLLUP_TITLE.search("MC1: Message Center rollup: 2026-07") is None


def test_months_run_from_the_starts_month_to_the_one_before_the_end():
    start = datetime(2026, 11, 15, 9, 30, tzinfo=UTC)
    found = months(start, datetime(2027, 1, 1, tzinfo=UTC))
    assert found == [
        ("2026-11", datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)),
        ("2026-12", datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    assert [name for name, *_ in months(start, datetime(2027, 1, 1, 0, 1, tzinfo=UTC))] == [
        "2026-11",
        "2026-12",
        "2027-01",
    ]
    assert months(start, start) == []
