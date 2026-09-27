"""Atlassian Cloud: the shared layer Jira and Confluence build on.

Its config section (``[atlassian]``: sites and the account to read each as), the API
token credential, and the client base. Depends only on ``core``. Public API::

    from libre_devops_helpers.atlassian import AtlassianServiceClient, profile_from_env
    from libre_devops_helpers.atlassian.jira import JiraClient

    profile = profile_from_env()  # JIRA_INSTANCE, JIRA_EMAIL (and JIRA_TOKEN)
    with JiraClient.for_profile(profile, os.environ) as jira:
        for issue in jira.issues("project = OPS AND statusCategory != Done"):
            print(issue.key, issue.status, issue.summary)
"""

from libre_devops_helpers.atlassian.client import (
    ERROR_HINTS,
    TOKEN_PAGE,
    ApiToken,
    AtlassianServiceClient,
    token_for,
)
from libre_devops_helpers.atlassian.config import (
    CONFIG_TEMPLATE,
    EMAIL_ENV,
    ENV_PROFILE,
    SECTION,
    SITE_ENV,
    TOKEN_ENV,
    AtlassianConfig,
    Profile,
    from_file,
    load_config,
    profile_from_env,
    site_url,
)

__all__ = [
    "CONFIG_TEMPLATE",
    "EMAIL_ENV",
    "ENV_PROFILE",
    "ERROR_HINTS",
    "SECTION",
    "SITE_ENV",
    "TOKEN_ENV",
    "TOKEN_PAGE",
    "ApiToken",
    "AtlassianConfig",
    "AtlassianServiceClient",
    "Profile",
    "from_file",
    "load_config",
    "profile_from_env",
    "site_url",
    "token_for",
]
