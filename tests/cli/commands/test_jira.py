import json

from fakes.atlassian import ENV, FakeSite
from fakes.tenant import run


def jira(config_file, *args, environ=None):
    return run(
        config_file, FakeSite(), ["jira", *args], environ=ENV if environ is None else environ
    )


def test_whoami_says_the_account_and_site(config_file):
    result = jira(config_file, "whoami")
    assert result.exit_code == 0, result.output
    assert "https://contoso.atlassian.net" in result.stdout
    assert "Ana" in result.stdout
    record = json.loads(jira(config_file, "whoami", "-o", "json").stdout)
    assert (record["profile"], record["active"]) == ("env", True)


def test_issues_come_from_a_query_or_a_project(config_file):
    result = jira(config_file, "issues", "--project", "ops", "-n", "2", "-o", "csv")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "KEY,TYPE,STATUS,PRIORITY,ASSIGNEE,UPDATED,SUMMARY"
    assert lines[2].startswith("OPS-2,Task,In Progress,Medium,-,")
    assert "2 issue(s) (profile env)" in result.stderr
    both = jira(config_file, "issues", "project = OPS", "--project", "OPS")
    assert both.exit_code == 2
    bad = jira(config_file, "issues", "--project", "OPS'--")
    assert bad.exit_code == 2


def test_an_issue_shows_its_details_then_its_description(config_file):
    result = jira(config_file, "issue", "OPS-1")
    assert result.exit_code == 0, result.output
    assert "Link      https://contoso.atlassian.net/browse/OPS-1" in result.stdout
    assert result.stdout.rstrip().endswith("Patch **web01** tonight.\n\n- drain")
    assert (
        jira(config_file, "issue", "OPS-1", "--markdown").stdout
        == "Patch **web01** tonight.\n\n- drain\n"
    )
    record = json.loads(jira(config_file, "issue", "OPS-1", "-o", "json").stdout)
    assert (record["key"], record["description"]) == (
        "OPS-1",
        "Patch **web01** tonight.\n\n- drain",
    )


def test_projects_and_no_profile(config_file):
    assert (
        jira(config_file, "projects", "-o", "csv")
        .stdout.splitlines()[1]
        .startswith("OPS,Operations,")
    )
    missing = jira(config_file, "projects", environ={})
    assert "no Atlassian profile selected" in str(missing.exception)
