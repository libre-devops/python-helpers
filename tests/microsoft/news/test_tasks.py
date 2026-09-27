from fakes.planner import message
from libre_devops_helpers.microsoft.news import Layout, Message, task_notes, task_title


def post(**changes) -> Message:
    return Message.from_json({**message("MC1000003", "Sentinel: connector\n retired"), **changes})


def test_a_title_holds_the_services_the_title_and_the_id_or_the_id_first():
    found = post(services=["Microsoft Sentinel", "Microsoft Defender XDR"])
    assert task_title(found, Layout.SYNC, limit=255) == (
        "[Microsoft Sentinel, Microsoft Defender XDR] Sentinel: connector retired [MC1000003]"
    )
    assert task_title(post(services=[]), Layout.SYNC, limit=255) == (
        "Sentinel: connector retired [MC1000003]"
    )
    assert task_title(found, Layout.SHORT, limit=255) == "MC1000003: Sentinel: connector retired"


def test_a_long_title_is_cut_but_never_its_id():
    long = post(title="word " * 80, services=["Microsoft Teams"])
    title = task_title(long, Layout.SYNC, limit=255)
    assert 240 < len(title) <= 255
    assert title.startswith("[Microsoft Teams] word word")
    assert title.endswith("word... [MC1000003]")
    short = task_title(long, Layout.SHORT, limit=60)
    assert len(short) <= 60
    assert short.startswith("MC1000003: word")
    assert short.endswith("word...")
    crowded = post(services=[f"Service number {n}" for n in range(20)])
    assert task_title(crowded, Layout.SYNC, limit=100) == "Sentinel: connector retired [MC1000003]"


def test_the_sync_notes_start_as_microsofts_sync_writes_them():
    notes = task_notes(
        post(category="stayInformed", tags=["Admin impact", "Feature update"]), Layout.SYNC
    )
    assert notes.startswith(
        "Message ID: MC1000003\n"
        "Published date: 9/20/2026\n"
        "Category: Stay informed\n"
        "Tags: Admin impact, Feature update\n"
        "\n"
        "https://admin.microsoft.com/#/MessageCenter/:/messages/MC1000003\n"
        "\n"
        "Sentinel: connector"
    )
    bare = Message.from_json({"id": "MC7", "title": "Quiet"})
    assert task_notes(bare, Layout.SYNC) == (
        "Message ID: MC7\n\nhttps://admin.microsoft.com/#/MessageCenter/:/messages/MC7"
    )
    assert (
        task_notes(bare, Layout.SHORT)
        == "https://admin.microsoft.com/#/MessageCenter/:/messages/MC7"
    )
