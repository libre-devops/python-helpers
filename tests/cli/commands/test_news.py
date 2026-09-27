import json

from fakes.planner import FakePlanner
from fakes.tenant import run
from libre_devops_helpers.core.errors import ApiError, InputError


def news(config_file, *args, fake=None):
    fake = fake or FakePlanner()
    return run(config_file, fake, ["news", *args]), fake


def test_posts_by_service_and_security_most_recent_first(config_file):
    result, _ = news(config_file, "messages", "--service", "xdr", "-o", "csv")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "ID,UPDATED,CATEGORY,SEVERITY,SERVICES,ACTION BY,TITLE"
    assert [line.split(",")[0] for line in lines[1:]] == ["MC1000001"]
    assert "1 post(s) changed in the last 30d" in result.stderr
    security, _ = news(config_file, "messages", "--security", "-o", "json")
    assert [item["id"] for item in json.loads(security.stdout)] == ["MC1000001", "MC1000003"]


def test_a_date_is_a_day_a_span_or_a_length_of_time(config_file):
    day, fake = news(config_file, "messages", "--date", "2026-09-26")
    assert day.exit_code == 0, day.output
    query = fake.requests[-1][1]
    assert "lastModifiedDateTime ge 2026-09-26T00:00:00Z" in query
    assert "lastModifiedDateTime lt 2026-09-27T00:00:00Z" in query
    assert "changed 2026-09-26" in day.stderr
    week, fake = news(config_file, "messages", "--date", "7d")
    assert "lastModifiedDateTime lt" not in fake.requests[-1][1]
    assert "changed in the last 7d" in week.stderr
    both, _ = news(config_file, "messages", "--date", "today", "--since", "7d")
    assert both.exit_code == 2
    unclear, _ = news(config_file, "messages", "--date", "01/02/2026")
    assert isinstance(unclear.exception, InputError)


def test_one_post_is_its_details_then_its_text(config_file):
    result, _ = news(config_file, "message", "MC1000003")
    assert result.exit_code == 0, result.output
    assert "Major change  yes" in result.stdout
    assert result.stdout.rstrip().endswith("Sentinel: connector retired: **act** by Friday.")
    markdown, _ = news(config_file, "message", "MC1000003", "--markdown")
    assert markdown.stdout == "Sentinel: connector retired: **act** by Friday.\n"
    record = json.loads(news(config_file, "message", "MC1000003", "-o", "json")[0].stdout)
    assert (record["id"], record["major"], record["body"]) == (
        "MC1000003",
        True,
        "Sentinel: connector retired: **act** by Friday.",
    )


def test_without_the_scope_it_says_to_use_your_own_app(config_file):
    fake = FakePlanner()
    fake.forbid_news = True
    result, _ = news(config_file, "messages", fake=fake)
    assert isinstance(result.exception, ApiError)
    assert "your own app registration" in result.exception.hint
