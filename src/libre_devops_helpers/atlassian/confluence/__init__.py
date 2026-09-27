"""Confluence Cloud: spaces, pages (their bodies as Markdown) and CQL search, as the
account whose API token the profile names.

Depends only on ``core`` and the shared Atlassian layer. Public API::

    from libre_devops_helpers.atlassian.confluence import ConfluenceClient

    with ConfluenceClient.for_profile(profile, os.environ) as confluence:
        for page in confluence.pages(space="OPS", limit=10):
            print(page.id, page.title)
        print(confluence.page("123456").body)
"""

from libre_devops_helpers.atlassian.confluence.client import ConfluenceClient
from libre_devops_helpers.atlassian.confluence.models import Page, SearchHit, Space

# Nothing past the token: it reads what its account may, in Confluence's own permissions.
REQUIREMENTS: tuple[str, ...] = ()

__all__ = ["REQUIREMENTS", "ConfluenceClient", "Page", "SearchHit", "Space"]
