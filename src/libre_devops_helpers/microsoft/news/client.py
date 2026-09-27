"""Message Center, through Graph's serviceAnnouncement: the posts, newest change first."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.core.util import odata_datetime, odata_string
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.news.models import CATEGORIES, Message

_PATH = "/v1.0/admin/serviceAnnouncement/messages"
_MESSAGE_ID = re.compile(r"MC[0-9]{1,12}")
SCOPE_HINT = (
    "Message Center needs ServiceMessage.Read.All, which the Azure CLI's token lacks: use a "
    "profile with your own app registration (-p)"
)


class NewsClient(GraphServiceClient):
    """Reads Message Center posts. Close it (or use ``with``) when done."""

    API_NAME = "Message Center (Microsoft Graph)"

    def messages(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        services: Sequence[str] = (),
        category: str | None = None,
        major: bool = False,
        limit: int | None = None,
    ) -> list[Message]:
        """Posts changed from ``since`` and before ``until`` (either end open when None),
        newest change first: for any of ``services`` (part of a name, ignoring case), in one
        ``category``, and only major changes with ``major``, when given."""
        clauses = []
        if since is not None:
            clauses.append(f"lastModifiedDateTime ge {odata_datetime(since)}")
        if until is not None:
            clauses.append(f"lastModifiedDateTime lt {odata_datetime(until)}")
        if category:
            clauses.append(f"category eq {odata_string(_category(category))}")
        if major:
            clauses.append("isMajorChange eq true")
        params = {"$select": Message.SELECT, "$orderby": "lastModifiedDateTime desc"}
        if clauses:
            params["$filter"] = " and ".join(clauses)
        found: list[Message] = []
        with _scoped():
            # Graph matches a service by its whole name only, so part of one is matched here.
            for item in self.api.get_all(_PATH, params=params):
                message = Message.from_json(item)
                if services and not message.for_any(services):
                    continue
                found.append(message)
                if limit is not None and len(found) >= limit:
                    break
        return found

    def message(self, message_id: str) -> Message:
        """One post, by its id (``MC1183010``)."""
        wanted = message_id.strip().upper()
        if not _MESSAGE_ID.fullmatch(wanted):
            raise InputError(f"{message_id!r} is not a Message Center id", hint="e.g. MC1183010")
        with _scoped():
            return Message.from_json(self.api.get(f"{_PATH}/{wanted}"))


@contextmanager
def _scoped() -> Iterator[None]:
    """A refusal says what Message Center needs, which is most often what is missing."""
    try:
        yield
    except ApiError as exc:
        if exc.status not in {401, 403}:
            raise
        raise ApiError(
            str(exc), status=exc.status, code=exc.code, request_id=exc.request_id, hint=SCOPE_HINT
        ) from None


def _category(value: str) -> str:
    """Graph's name for a category, from it or from how it reads (``plan for change``)."""
    folded = value.strip().casefold().replace(" ", "").replace("-", "")
    for name in CATEGORIES:
        if name.casefold() == folded:
            return name
    raise InputError(
        f"{value!r} is not a Message Center category",
        hint="use one of: " + ", ".join(CATEGORIES.values()),
    )
