"""Microsoft 365 Message Center: the posts announcing what changes in the tenant's services.

Through Graph's ``admin/serviceAnnouncement/messages``, which needs ServiceMessage.Read.All
(delegated, or an application role): the Azure CLI's token has neither, so use a profile
with your own app registration. Depends only on ``core`` and the shared Microsoft layer.
Public API::

    from libre_devops_helpers.microsoft.news import NewsClient

    with NewsClient.create(tokens, tenant_id) as news:
        for message in news.messages(since=last_week, major=True):
            print(message.id, message.title)

A month's posts summed up for one Planner task: ``Rollup(month, messages)``, with
``months(start, end)`` for the months a span touches and ``listed(description)`` for the
posts a rollup has already. A task for one post: ``task_title`` and ``task_notes``, in a
``Layout``.
"""

from libre_devops_helpers.microsoft.news.client import SCOPE_HINT, NewsClient
from libre_devops_helpers.microsoft.news.models import (
    ADMIN_CENTRE,
    CATEGORIES,
    MESSAGE_KEY,
    SECURITY_SERVICES,
    Message,
)
from libre_devops_helpers.microsoft.news.permissions import REQUIREMENTS
from libre_devops_helpers.microsoft.news.rollup import ROLLUP_TITLE, Rollup, listed, months
from libre_devops_helpers.microsoft.news.tasks import TEXT_LIMIT, Layout, task_notes, task_title

__all__ = [
    "ADMIN_CENTRE",
    "CATEGORIES",
    "MESSAGE_KEY",
    "REQUIREMENTS",
    "ROLLUP_TITLE",
    "SCOPE_HINT",
    "SECURITY_SERVICES",
    "TEXT_LIMIT",
    "Layout",
    "Message",
    "NewsClient",
    "Rollup",
    "listed",
    "months",
    "task_notes",
    "task_title",
]
