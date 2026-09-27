import pytest

from fakes.atlassian import EMAIL, ENV, SITE, FakeSite
from fakes.http import fake_session
from libre_devops_helpers.atlassian import Profile
from libre_devops_helpers.atlassian.jira import DEFAULT_JQL, JiraClient
from libre_devops_helpers.core.errors import ApiError, InputError


def jira(site=None):
    session, _ = fake_session(site or FakeSite())
    return JiraClient.for_profile(Profile("work", SITE, EMAIL), ENV, session=session)


def test_a_search_follows_its_page_tokens_up_to_the_limit():
    site = FakeSite()
    with jira(site) as client:
        found = client.issues("project = OPS", limit=4)
        assert [item.key for item in found] == ["OPS-1", "OPS-2", "OPS-3", "OPS-4"]
        assert client.issues(limit=100)[-1].key == "OPS-5"
    assert any("nextPageToken" not in url for url in site.requests)
    with pytest.raises(ValueError, match="limit must be at least 1"):
        jira().issues(limit=0)


def test_an_unbounded_search_is_refused_with_jiras_reason():
    with pytest.raises(ApiError, match="Unbounded JQL"):
        jira().issues("ORDER BY updated")
    assert DEFAULT_JQL.startswith("statusCategory != Done")


def test_one_issue_has_its_description_as_markdown():
    found = jira().issue("ops-1")
    assert (found.key, found.url) == ("OPS-1", f"{SITE}/browse/OPS-1")
    assert found.description == "Patch **web01** tonight.\n\n- drain"
    with pytest.raises(InputError):
        jira().issue("OPS 1")
    with pytest.raises(ApiError, match="Issue does not exist"):
        jira().issue("OPS-99")


def test_projects_are_every_page_of_them_and_who_am_i():
    with jira() as client:
        assert [project.key for project in client.projects()] == ["OPS", "SEC"]
        assert client.whoami()["displayName"] == "Ana"
