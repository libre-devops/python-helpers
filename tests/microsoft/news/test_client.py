from datetime import UTC, datetime

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.planner import FakePlanner
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.microsoft.news import SECURITY_SERVICES, NewsClient


def news(fake=None):
    fake = fake or FakePlanner()
    session, _ = fake_session(fake)
    return NewsClient.create(StaticTokens(), TENANT, session=session), fake


def test_posts_are_asked_for_by_change_time_category_and_major_and_matched_by_part_of_a_service():
    client, fake = news()
    since, until = datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 27, tzinfo=UTC)
    found = client.messages(since=since, until=until, services=["xdr", "SENTINEL"])
    assert [message.id for message in found] == ["MC1000001", "MC1000003"]
    query = fake.requests[-1][1]
    assert "lastModifiedDateTime ge 2026-09-20T00:00:00Z" in query
    assert "lastModifiedDateTime lt 2026-09-27T00:00:00Z" in query
    assert "$orderby=lastModifiedDateTime desc" in query
    assert [m.id for m in client.messages(major=True)] == ["MC1000003"]
    assert client.messages(category="stay informed") == []
    assert len(client.messages(limit=2)) == 2
    assert [m.id for m in client.messages(services=SECURITY_SERVICES)] == ["MC1000001", "MC1000003"]
    with pytest.raises(InputError, match="not a Message Center category"):
        client.messages(category="news")


def test_one_post_by_its_id_and_a_refusal_says_what_is_needed():
    client, fake = news()
    found = client.message("mc1000003")
    assert (found.id, found.severity, found.major) == ("MC1000003", "high", True)
    with pytest.raises(InputError):
        client.message("1000003")
    fake.forbid_news = True
    with pytest.raises(ApiError) as error:
        client.messages()
    assert "ServiceMessage.Read.All" in error.value.hint
    fake.forbid_news = False
    with pytest.raises(ApiError, match="no such message") as missing:
        client.message("MC9")
    assert "ServiceMessage.Read.All" not in (missing.value.hint or "")
