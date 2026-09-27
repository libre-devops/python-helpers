from datetime import UTC, datetime

from fakes.atlassian import SITE, issue
from libre_devops_helpers.atlassian.jira import Issue, Project


def test_an_issue_reads_every_field_and_tolerates_the_missing_ones():
    found = Issue.from_api(issue("OPS-7", "Patch", "Done", "Done"), SITE)
    assert (found.status, found.status_category, found.assignee, found.labels) == (
        "Done",
        "Done",
        "Ana",
        ("linux",),
    )
    assert found.updated == datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
    bare = Issue.from_api({"key": "OPS-8", "fields": {}}, SITE)
    assert (bare.assignee, bare.priority, bare.created) == ("", "", None)


def test_a_project_links_to_its_board():
    found = Project.from_api(
        {"id": "1", "key": "OPS", "name": "Ops", "projectTypeKey": "software"}, SITE
    )
    assert found.url == f"{SITE}/browse/OPS"
