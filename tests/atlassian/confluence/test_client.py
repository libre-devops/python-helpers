import pytest

from fakes.atlassian import EMAIL, ENV, SITE, FakeSite
from fakes.http import fake_session
from libre_devops_helpers.atlassian import Profile
from libre_devops_helpers.atlassian.confluence import ConfluenceClient
from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError


def confluence():
    session, _ = fake_session(FakeSite())
    return ConfluenceClient.for_profile(Profile("work", SITE, EMAIL), ENV, session=session)


def test_spaces_are_every_page_of_them():
    found = confluence().spaces()
    assert [space.key for space in found] == ["OPS", "~acc1"]
    assert found[0].url == f"{SITE}/wiki/spaces/OPS"


def test_pages_come_from_a_space_by_its_key_or_from_every_space():
    assert [page.title for page in confluence().pages(space="OPS")] == ["Runbook", "On-call"]
    assert [page.title for page in confluence().pages(space="~acc1")] == ["Notes"]
    assert [page.title for page in confluence().pages(title="On-call")] == ["On-call"]
    assert len(confluence().pages(limit=2)) == 2
    with pytest.raises(NotFoundError):
        confluence().pages(space="NOPE")
    with pytest.raises(InputError):
        confluence().space("OPS/../x")
    with pytest.raises(ValueError, match="limit must be at least 1"):
        confluence().pages(limit=0)


def test_a_page_has_its_body_as_markdown():
    found = confluence().page("101")
    assert found.body == "## Restart\n\nRun `systemctl restart app`."
    assert (found.version, found.url) == (3, f"{SITE}/wiki/spaces/OPS/pages/101/Runbook")
    with pytest.raises(InputError):
        confluence().page("10a")
    with pytest.raises(ApiError, match="Not Found: no such page"):
        confluence().page("999")


def test_search_finds_with_cql_up_to_the_limit():
    (hit,) = confluence().search('type = page AND text ~ "restart"')
    assert (hit.title, hit.space, hit.excerpt) == ("Runbook", "Operations", "restart the app")
    assert hit.url == f"{SITE}/wiki/spaces/OPS/pages/101/Runbook"
    with pytest.raises(ValueError, match="limit must be at least 1"):
        confluence().search("type = page", limit=0)
