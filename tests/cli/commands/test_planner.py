import json

from fakes.planner import FakePlanner, message, task
from fakes.tenant import run, usage_error


def planner(config_file, *args, fake=None):
    fake = fake or FakePlanner()
    return run(config_file, fake, ["planner", *args]), fake


def test_plans_buckets_and_tasks(config_file):
    plans, _ = planner(config_file, "plans", "-o", "csv")
    assert plans.stdout.splitlines()[1].startswith("Operations,")
    buckets, _ = planner(config_file, "buckets", "Operations", "-o", "csv")
    assert buckets.stdout.splitlines()[1:] == [
        "To be discussed,BucketDiscussAAAAAAAAAAAAAAA",
        "Closed,BucketClosedAAAAAAAAAAAAAAAA",
    ]
    everything, _ = planner(config_file, "tasks", "Operations", "-o", "json")
    assert [task["bucket"] for task in json.loads(everything.stdout)] == [
        "Closed",
        "To be discussed",
    ]
    open_ones, _ = planner(
        config_file, "tasks", "Operations", "--open", "--bucket", "to be discussed", "-o", "csv"
    )
    assert open_ones.stdout.splitlines()[1].startswith(
        "Message Center rollup: 2026-09 (3 messages),To be discussed,0%,"
    )


def test_add_news_says_which_posts_it_would_raise_and_raises_nothing(config_file):
    result, fake = planner(
        config_file, "add-news", "Operations", "--bucket", "To be discussed", "-o", "csv"
    )
    assert result.exit_code == 3, result.output
    rows = result.stdout.splitlines()[1:]
    assert [row.split(",")[0] for row in rows] == ["MC1000001", "MC1000002", "MC1000003"]
    states = [line.rsplit(",", 1)[1] for line in result.stdout.splitlines()[1:]]
    assert states == ["raised already", "to raise", "to raise"]
    assert "2 to raise in Operations / To be discussed, 1 raised already" in result.stderr
    assert not any(method == "POST" for method, _ in fake.requests)


def test_add_news_with_write_raises_each_missing_post_once_with_its_link(config_file):
    args = [
        "add-news",
        "Operations",
        "--bucket",
        "To be discussed",
        "--security",
        "--write",
        "-o",
        "json",
    ]
    result, fake = planner(config_file, *args)
    assert result.exit_code == 0, result.output
    assert [item["task"] for item in json.loads(result.stdout)] == ["raised already", "raised"]
    made = fake.tasks[-1]
    assert (made["title"], made["bucketId"]) == (
        "[Microsoft Sentinel] Sentinel: connector retired [MC1000003]",
        "BucketDiscussAAAAAAAAAAAAAAA",
    )
    description = fake.details[made["id"]]["description"]
    assert description.startswith(
        "Message ID: MC1000003\n"
        "Published date: 9/20/2026\n"
        "Category: Plan for change\n"
        "Tags: Admin impact\n"
        "\n"
        "https://admin.microsoft.com/#/MessageCenter/:/messages/MC1000003\n\n"
    )
    assert "raised 1 task(s) in Operations / To be discussed; 1 had one" in result.stderr
    again, fake = planner(config_file, *args, fake=fake)
    assert [item["task"] for item in json.loads(again.stdout)] == [
        "raised already",
        "raised already",
    ]


def test_the_short_layout_titles_a_task_by_the_posts_id_first(config_file):
    args = ["add-news", "Operations", "--bucket", "To be discussed", "--service", "sentinel"]
    result, fake = planner(config_file, *args, "--layout", "SHORT", "--write")
    assert result.exit_code == 0, result.output
    made = fake.tasks[-1]
    assert made["title"] == "MC1000003: Sentinel: connector retired"
    assert fake.details[made["id"]]["description"].startswith(
        "https://admin.microsoft.com/#/MessageCenter/:/messages/MC1000003\n\n"
    )


def test_a_long_post_is_cut_to_fit_a_description(config_file):
    fake = FakePlanner()
    fake.messages[2]["body"]["content"] = "<p>" + "word " * 3000 + "</p>"
    args = [
        "add-news",
        "Operations",
        "--bucket",
        "To be discussed",
        "--service",
        "sentinel",
        "--write",
    ]
    result, fake = planner(config_file, *args, fake=fake)
    assert result.exit_code == 0, result.output
    description = next(iter(fake.details.values()))["description"]
    assert description.endswith("(more in the admin centre)")


def test_add_news_counts_a_task_titled_as_microsofts_own_sync_titles_them(config_file):
    fake = FakePlanner()
    fake.tasks.append(task("TaskSyncAAAAAAAAAAAAAAAAAAAA", "[Microsoft Teams] recap [MC1000002]"))
    result, _ = planner(
        config_file,
        "add-news",
        "Operations",
        "--bucket",
        "To be discussed",
        "-o",
        "json",
        fake=fake,
    )
    assert [item["task"] for item in json.loads(result.stdout)] == [
        "raised already",
        "raised already",
        "to raise",
    ]


ROLLUP = ["add-rollup", "Operations", "--bucket", "To be discussed"]


def test_add_rollup_says_which_months_it_would_raise_or_update(config_file):
    fake = FakePlanner()
    fake.messages.append(message("MC999", "August post", updated="2026-08-31T10:00:00Z"))
    result, fake = planner(
        config_file, *ROLLUP, "--date", "2026-08-30..2026-09-02", "-o", "csv", fake=fake
    )
    assert result.exit_code == 3, result.output
    assert result.stdout.splitlines()[1:] == ["2026-08,1,1,to raise", "2026-09,3,3,to update"]
    assert "1 to raise and 1 to update in Operations / To be discussed, 0 up to date" in (
        result.stderr
    )
    assert not any(method in {"POST", "PATCH"} for method, _ in fake.requests)


def test_add_rollup_with_write_raises_and_updates_then_finds_them_up_to_date(config_file):
    fake = FakePlanner()
    fake.messages.append(message("MC999", "August post", updated="2026-08-31T10:00:00Z"))
    args = [*ROLLUP, "--date", "2026-08-30..2026-09-02", "--write", "-o", "json"]
    result, fake = planner(config_file, *args, fake=fake)
    assert result.exit_code == 0, result.output
    assert [(item["month"], item["task"]) for item in json.loads(result.stdout)] == [
        ("2026-08", "raised"),
        ("2026-09", "updated"),
    ]
    raised = fake.tasks[-1]
    assert (raised["title"], raised["bucketId"]) == (
        "Message Center rollup: 2026-08 (1 message)",
        "BucketDiscussAAAAAAAAAAAAAAA",
    )
    assert fake.details[raised["id"]]["description"].endswith(
        "- MC999 2026-08-31 [Microsoft Defender XDR] August post"
    )
    updated = fake.details["TaskTwoAAAAAAAAAAAAAAAAAAAAA"]["description"]
    assert updated.startswith("# Message Center summary (2026-09)\n\nTotal: 3 messages")
    assert "raised 1 and updated 1 rollup(s) in Operations / To be discussed" in result.stderr
    again, fake = planner(config_file, *args, fake=fake)
    assert again.exit_code == 0, again.output
    assert [(item["task"], item["new"]) for item in json.loads(again.stdout)] == [
        ("up to date", 0),
        ("up to date", 0),
    ]
    fake.messages.append(message("MC1000004", "Later post", updated="2026-09-01T12:00:00Z"))
    later, fake = planner(config_file, *args, fake=fake)
    assert [(item["task"], item["new"]) for item in json.loads(later.stdout)] == [
        ("up to date", 0),
        ("updated", 1),
    ]
    assert fake.tasks[1]["title"] == "Message Center rollup: 2026-09 (4 messages)"
    fake.messages = [item for item in fake.messages if item["id"] != "MC1000002"]
    gone, fake = planner(config_file, *args, fake=fake)
    assert [item["task"] for item in json.loads(gone.stdout)] == ["up to date", "updated"]
    kept = fake.details["TaskTwoAAAAAAAAAAAAAAAAAAAAA"]["description"]
    messages, earlier = kept.split("\n\n## Listed before\n")
    assert "MC1000002" not in messages
    assert earlier.endswith("\n- MC1000002 2026-09-26 [Microsoft Teams] Teams: meeting recap")
    assert fake.tasks[1]["title"] == "Message Center rollup: 2026-09 (3 messages)"
    steady, fake = planner(config_file, *args, fake=fake)
    assert [item["task"] for item in json.loads(steady.stdout)] == ["up to date", "up to date"]


def test_add_rollup_needs_a_first_day_and_says_when_there_is_nothing(config_file):
    open_ended, _ = planner(config_file, *ROLLUP, "--date", "..2026-09-14")
    assert open_ended.exit_code == 2
    assert "give the first day" in usage_error(open_ended)
    quiet, _ = planner(config_file, *ROLLUP, "--date", "2026-01-10")
    assert quiet.exit_code == 0, quiet.output
    assert "no posts in those months, so no rollup for Operations / To be discussed" in (
        quiet.stderr
    )
