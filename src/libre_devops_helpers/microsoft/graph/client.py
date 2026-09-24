"""Microsoft Graph, directly: any GET, paged; objects by name or id; Advanced Hunting.

The feature modules (entra, intune, incidents, pim) each read the part of Graph they
need. This one is the general tool: read any path, as ``az rest`` would, but knowing
Graph's paging, its query options and the ``ConsistencyLevel`` its advanced queries
want. It only reads: the one POST, ``runHuntingQuery``, runs a query and changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Self
from urllib.parse import quote, urlsplit

import requests

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.tables import QueryResult
from libre_devops_helpers.core.util import candidate_names, is_guid, odata_string
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile

VERSIONS = ("v1.0", "beta")
HUNT_HINT = (
    "Advanced Hunting through Graph needs ThreatHunting.Read.All on the token, which the "
    "Azure CLI's token never carries: use an interactive or device-code profile whose app "
    f"has it (or {brand.command('xdr hunt --endpoint')}, for the device tables with the "
    "Azure CLI's sign-in)"
)
_UNSAFE = re.compile(r"[\s\\]|\.\.")

# What each kind of object is looked up by, besides its id.
KINDS = {
    "user": ("users", ("userPrincipalName", "displayName", "mail")),
    "device": ("devices", ("displayName",)),
    "group": ("groups", ("displayName", "mailNickname")),
    "app": ("applications", ("displayName",)),
    "sp": ("servicePrincipals", ("displayName",)),
}


@dataclass(frozen=True)
class GraphPage:
    """What a collection GET returned: its items, and more if there is more."""

    items: tuple[dict[str, Any], ...]
    count: int | None = None  # @odata.count, when asked for with --count
    more: bool = False  # a next page exists that was not fetched


class GraphClient:
    """Reads Microsoft Graph for one tenant. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        graph_url: str = PUBLIC.graph_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        api = ApiClient(
            graph_url,
            token_source(tokens, graph_url, tenant_id),
            name="Microsoft Graph",
            verify=verify,
            session=session,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> Self:
        return cls.create(
            tokens,
            profile.tenant_id,
            graph_url=profile.cloud.graph_url,
            verify=verify,
            session=session,
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Any path ------------------------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        beta: bool = False,
        eventual: bool = False,
    ) -> dict[str, Any]:
        """GET ``path`` (``users``, ``/beta/me``, or a full Graph URL) once."""
        headers = {"ConsistencyLevel": "eventual"} if eventual else None
        return self.api.get(graph_path(path, beta=beta), params=params, headers=headers)

    def page(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        beta: bool = False,
        eventual: bool = False,
        limit: int | None = None,
        all_pages: bool = False,
    ) -> GraphPage:
        """A collection's items: the first page, up to ``limit``, or every page."""
        data = self.get(path, params=params, beta=beta, eventual=eventual)
        if not isinstance(data.get("value"), list):
            raise InputError(f"{path} is a single object, not a collection")
        items: list[dict[str, Any]] = []
        count = data.get("@odata.count")
        while True:
            items.extend(item for item in data["value"] if isinstance(item, dict))
            link = data.get("@odata.nextLink")
            if limit is not None and len(items) >= limit:
                return GraphPage(tuple(items[:limit]), count, bool(link) or len(items) > limit)
            if not isinstance(link, str) or not link:
                return GraphPage(tuple(items), count)
            if not all_pages and limit is None:
                return GraphPage(tuple(items), count, more=True)
            headers = {"ConsistencyLevel": "eventual"} if eventual else None
            data = self.api.get(link, headers=headers)

    # Objects by name or id -----------------------------------------------------------

    def lookup(self, kind: str, ref: str, *, select: str | None = None) -> list[dict[str, Any]]:
        """Every object of ``kind`` that ``ref`` names: an id, or a name it goes by.

        Devices are tried by FQDN, then short host name, as elsewhere in this tool; a
        name can match several objects (stale device registrations keep the name).
        """
        if kind not in KINDS:
            raise InputError(f"unknown kind {kind!r}: use one of {', '.join(KINDS)}")
        collection, fields = KINDS[kind]
        ref = ref.strip()
        if not ref:
            raise InputError(f"no {kind} named")
        params = {"$select": select} if select else {}
        if is_guid(ref):
            return self._by_id(kind, collection, ref, params)
        if kind == "user" and "@" in ref:
            try:
                return [self.get(f"users/{quote(ref, safe='@')}", params=params)]
            except ApiError as exc:
                if exc.status != 404:
                    raise
        names = candidate_names(ref) if kind == "device" else [ref]
        for name in names:
            either = " or ".join(f"{field} eq {odata_string(name)}" for field in fields)
            found = self.page(
                collection, params={**params, "$filter": either}, all_pages=True
            ).items
            if found:
                return list(found)
        return []

    def _by_id(
        self, kind: str, collection: str, ref: str, params: Mapping[str, str]
    ) -> list[dict[str, Any]]:
        try:
            return [self.get(f"{collection}/{ref}", params=params)]
        except ApiError as exc:
            if exc.status != 404:
                raise
        # Not an object id: for these kinds, the other id people use.
        other = {"device": "deviceId", "app": "appId", "sp": "appId"}.get(kind)
        if other is None:
            return []
        expression = f"{other} eq {odata_string(ref)}"
        return list(self.page(collection, params={**params, "$filter": expression}).items)

    def me(self) -> dict[str, Any]:
        """The signed-in user (delegated tokens only)."""
        return self.get(
            "me",
            params={"$select": "id,displayName,userPrincipalName,mail,jobTitle,department"},
        )

    def service_principal(self, app_id: str) -> dict[str, Any] | None:
        """The service principal an app-only token belongs to, or None."""
        if not is_guid(app_id):
            return None
        found = self.page(
            "servicePrincipals",
            params={
                "$filter": f"appId eq {odata_string(app_id)}",
                "$select": "id,displayName,appId",
            },
        ).items
        return found[0] if found else None

    # Advanced Hunting ----------------------------------------------------------------

    def hunt(self, query: str, *, timespan: timedelta | None = None) -> QueryResult:
        """Run an Advanced Hunting (KQL) query over the whole Defender XDR schema."""
        if not query.strip():
            raise InputError("the hunting query is empty")
        body: dict[str, Any] = {"Query": query}
        if timespan is not None:
            body["Timespan"] = iso_duration(timespan)
        try:
            data = self.api.post("/v1.0/security/runHuntingQuery", body)
        except ApiError as exc:
            if exc.status in {401, 403} and not _suspended(exc):
                raise ApiError(
                    str(exc),
                    status=exc.status,
                    code=exc.code,
                    request_id=exc.request_id,
                    hint=HUNT_HINT,
                ) from None
            raise
        schema = data.get("schema") if isinstance(data.get("schema"), list) else []
        rows = [row for row in data.get("results") or () if isinstance(row, dict)]
        columns = [str(column.get("name")) for column in schema if isinstance(column, dict)]
        if not columns:
            return QueryResult.from_records(rows)
        return QueryResult(tuple(columns), tuple(rows))


def _suspended(exc: ApiError) -> bool:
    """A suspended service answers 403 too; that hint says why better than a scope one."""
    return "suspended" in str(exc).lower()


def graph_path(path: str, *, beta: bool = False) -> str:
    """``path`` as Graph wants it: ``users`` -> ``/v1.0/users``, ``beta/me`` kept as is.

    A full Graph URL (a nextLink, or one pasted from Graph Explorer) passes through; the
    API client refuses any other host, so the token cannot be sent elsewhere.
    """
    text = path.strip()
    if not text:
        raise InputError("no Graph path given", hint="for example: users, me, devices")
    if "://" in text:
        return text
    base = urlsplit(text).path.lstrip("/")
    if _UNSAFE.search(base):
        raise InputError(f"{path!r} is not a Graph path")
    first = base.split("/", 1)[0]
    if first in VERSIONS:
        if beta and first != "beta":
            raise InputError("--beta and a v1.0 path disagree")
        return "/" + text.lstrip("/")
    return f"/{'beta' if beta else 'v1.0'}/{text.lstrip('/')}"


def iso_duration(span: timedelta) -> str:
    """An ISO 8601 duration: ``P7D``, ``PT6H``, ``PT30M``, ``PT45S``."""
    seconds = int(span.total_seconds())
    if seconds <= 0:
        raise InputError("a timespan must be positive")
    if seconds % 86400 == 0:
        return f"P{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"PT{seconds // 3600}H"
    if seconds % 60 == 0:
        return f"PT{seconds // 60}M"
    return f"PT{seconds}S"


def not_found(kind: str, ref: str) -> NotFoundError:
    tried = (
        " or ".join(repr(name) for name in candidate_names(ref)) if kind == "device" else repr(ref)
    )
    return NotFoundError(f"no {kind} is named {tried}")
