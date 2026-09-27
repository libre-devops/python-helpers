import json

from fakes.planner import FakePlanner
from fakes.tenant import run


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
        "MC1000003: Sentinel: connector retired",
        "BucketDiscussAAAAAAAAAAAAAAA",
    )
    description = fake.details[made["id"]]["description"]
    assert description.startswith(
        "https://admin.microsoft.com/#/MessageCenter/:/messages/MC1000003\n\n"
    )
    assert "raised 1 task(s) in Operations / To be discussed; 1 had one" in result.stderr
    again, fake = planner(config_file, *args, fake=fake)
    assert [item["task"] for item in json.loads(again.stdout)] == [
        "raised already",
        "raised already",
    ]


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
