"""Jira Cloud: search issues with JQL, read one (its description as Markdown), and list
projects, as the account whose API token the profile names.

Depends only on ``core`` and the shared Atlassian layer. Public API::

    from libre_devops_helpers.atlassian.jira import JiraClient

    with JiraClient.for_profile(profile, os.environ) as jira:
        for issue in jira.issues("project = OPS AND statusCategory != Done", limit=20):
            print(issue.key, issue.status, issue.summary)
        print(jira.issue("OPS-12").description)
"""

from libre_devops_helpers.atlassian.jira.client import DEFAULT_JQL, FIELDS, JiraClient
from libre_devops_helpers.atlassian.jira.models import Issue, Project

# Nothing past the token: it reads what its account may, in Jira's own permissions.
REQUIREMENTS: tuple[str, ...] = ()

__all__ = ["DEFAULT_JQL", "FIELDS", "REQUIREMENTS", "Issue", "JiraClient", "Project"]
