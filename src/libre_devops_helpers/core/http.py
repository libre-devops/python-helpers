"""HTTP client for Microsoft APIs: bearer auth, bounded retries, Retry-After, paging.

Built on requests. Retries are decided on the HTTP status code (408, 429, 5xx) and on
connection errors or timeouts, never on the wording of an error message. The bearer
token is only ever sent to the client's own https host, and redirects are not followed.
Every POST this package makes is a read-only query or a token request, so retrying
one is safe. A 401 is retried once with a fresh token, when the token source can drop
the one it cached (``core.auth.BearerToken``).
"""

from __future__ import annotations

import email.utils
import ipaddress
import json
import logging
import random
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import SplitResult, quote, urlencode, urlsplit

import requests

from libre_devops_helpers import __version__
from libre_devops_helpers.core import brand, network
from libre_devops_helpers.core.errors import ApiError

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
USER_AGENT = f"{brand.COMMAND}/{__version__}"


class ApiClient:
    """JSON client for one API base URL, usually authenticated with a bearer token.

    ``token`` is called before every request, so a caching provider can refresh a token
    close to expiry. If it also has a ``refresh()`` method, a 401 answer drops the cached
    token and the request is sent once more with a new one: that covers a token revoked
    or expired early. Tokens go in the Authorization header only and are never logged.
    With ``token=None`` no Authorization header is sent; only then may ``allow_http``
    permit a plain http base URL on a loopback or link-local host, which is what the
    managed identity endpoints use.

    The proxy and certificates follow ``core.network``: ``network_settings`` when given,
    else the process's own (``network.configure``).
    """

    def __init__(
        self,
        base_url: str,
        token: Callable[[], str] | None,
        *,
        name: str = "API",
        session: requests.Session | None = None,
        verify: bool | str = True,
        timeout: float = 30.0,
        max_attempts: int = 4,
        backoff: float = 1.0,
        max_backoff: float = 30.0,
        max_retry_after: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        allow_http: bool = False,
        auth_scheme: str = "Bearer",
        network_settings: network.NetworkSettings | None = None,
        error_hints: Mapping[str, str] | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if not parts.netloc or parts.scheme not in {"https", "http"}:
            raise ValueError(f"base_url must be an https URL, got {base_url!r}")
        if parts.scheme == "http" and not (
            allow_http and token is None and _is_local(parts.hostname or "")
        ):
            raise ValueError(f"base_url must be an https URL, got {base_url!r}")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._origin = _origin(parts)
        self._token = token
        # "Bearer" for tokens; "Basic" when ``token`` returns base64 "user:password".
        self._auth_scheme = auth_scheme
        refresh = getattr(token, "refresh", None)
        self._refresh_token: Callable[[], None] | None = refresh if callable(refresh) else None
        self._session = session or requests.Session()
        self._owns_session = session is None
        if self._owns_session:
            # Proxies and certificates follow core.network's rules, not requests' own
            # reading of the environment, so they are the same for every call.
            self._session.trust_env = False
        # True means the combined bundle core.network resolves (the public roots, the OS
        # store and the config's ca_bundle); a path means that bundle exactly.
        self._verify = verify
        self._network = network_settings
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._max_retry_after = max_retry_after
        self._sleep = sleep
        # What to tell a person about an error code this API is known to give.
        self._error_hints = dict(error_hints or {})

    def ensure_token(self) -> None:
        """Get the token now, in this thread.

        Call it on the main thread before fanning requests out to workers, so that a
        credential which has to ask someone to sign in again asks there.
        """
        if self._token is not None:
            self._token()

    def close(self) -> None:
        """Close the underlying session if this client created it."""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def url(self, path: str, params: Mapping[str, str] | None = None) -> str:
        """Absolute URL for ``path`` with ``params`` percent-encoded.

        ``path`` may be a full URL (an ``@odata.nextLink``); it must use this client's
        scheme, host and port, so a token never travels anywhere else. The scheme's own port
        is the same as none: Resource Manager's next links name ``:443``.
        """
        if "://" in path:
            parts = urlsplit(path)
            if parts.username is not None or _origin(parts) != self._origin:
                raise ApiError(
                    f"{self.name}: refusing to send a token to {parts.scheme}://{parts.netloc}"
                )
            url = path
        else:
            url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, quote_via=quote)
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        """Send one request and return the JSON object it responds with.

        ``allow_empty`` accepts a success with no body (some actions answer 200 or 204
        with nothing), returning ``{}`` for it.
        """
        url = self.url(path, params)
        response = self._send(method, url, headers, json_body=json_body, form=form)
        if allow_empty and not response.content.strip():
            return {}
        try:
            body = response.json()
        except ValueError:
            raise ApiError(
                f"{self.name}: {method} {_path(url)} did not return JSON",
                status=response.status_code,
            ) from None
        if not isinstance(body, dict):
            raise ApiError(f"{self.name}: {method} {_path(url)} did not return a JSON object")
        return body

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET ``path`` and return the JSON object it responds with."""
        return self.request("GET", path, params=params, headers=headers)

    def get_text(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        """GET ``path`` and return its body as text, for the few APIs that answer in text."""
        response = self._send("GET", self.url(path, params), headers)
        return response.text

    def post(
        self,
        path: str,
        body: Any,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST ``body`` as JSON to ``path`` and return the JSON object it responds with."""
        return self.request("POST", path, params=params, headers=headers, json_body=body)

    def get_all(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        next_link: str = "@odata.nextLink",
    ) -> Iterator[dict[str, Any]]:
        """Yield every item of a paged collection, following ``next_link``.

        Graph and Defender use ``@odata.nextLink``; Azure Resource Manager and Key Vault
        use ``nextLink``. Pages are fetched only as items are consumed.
        """
        page = self.get(path, params=params, headers=headers)
        while True:
            items = page.get("value")
            if not isinstance(items, list):
                raise ApiError(f"{self.name}: response has no 'value' array")
            yield from (item for item in items if isinstance(item, dict))
            link = page.get(next_link)
            if not isinstance(link, str) or not link:
                return
            page = self.get(link, headers=headers)

    def _send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        *,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
    ) -> requests.Response:
        attempt = 0
        refreshed = False
        while True:
            attempt += 1
            request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
            if self._token is not None:
                request_headers["Authorization"] = f"{self._auth_scheme} {self._token()}"
            request_headers.update(headers or {})
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=request_headers,
                    json=json_body,
                    data=form,
                    timeout=self._timeout,
                    verify=self._verify_with(),
                    proxies=network.requests_proxies(url, self._network),
                    allow_redirects=False,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self._max_attempts:
                    raise ApiError(
                        f"{self.name}: {method} {_path(url)} failed after {attempt} attempts: "
                        f"{type(exc).__name__}"
                    ) from None
                self._wait(attempt, None, type(exc).__name__)
                continue
            except requests.RequestException as exc:
                raise ApiError(f"{self.name}: {method} {_path(url)} failed: {exc}") from None

            if 200 <= response.status_code < 300:
                return response
            if response.status_code == 401 and self._refresh_token and not refreshed:
                # Once only: a second 401 means the token is not the problem.
                refreshed = True
                attempt -= 1
                log.info("%s: HTTP 401, retrying once with a new token", self.name)
                self._refresh_token()
                continue
            if response.status_code in RETRY_STATUSES and attempt < self._max_attempts:
                self._wait(attempt, retry_after_seconds(response), f"HTTP {response.status_code}")
                continue
            raise error_from_response(self.name, response, self._error_hints)

    def _verify_with(self) -> bool | str:
        """What requests verifies against: the resolved bundle, or what was asked for."""
        return network.ca_bundle(self._network).path if self._verify is True else self._verify

    def _wait(self, attempt: int, retry_after: float | None, reason: str) -> None:
        # A server-directed Retry-After wins over the backoff (retrying earlier just
        # throttles again), capped so a broken server cannot stall the run.
        if retry_after is not None:
            delay = min(self._max_retry_after, retry_after)
        else:
            delay = min(self._max_backoff, self._backoff * 2 ** (attempt - 1))
            # Jitter, so clients that failed together do not retry together; not secret.
            delay += random.uniform(0, self._backoff / 2)  # noqa: S311
        log.warning(
            "%s: %s on attempt %d of %d, retrying in %.1fs",
            self.name,
            reason,
            attempt,
            self._max_attempts,
            delay,
        )
        self._sleep(delay)


def retry_after_seconds(response: requests.Response) -> float | None:
    """Seconds requested by a Retry-After header (delta-seconds or HTTP date), else None."""
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def error_from_response(
    name: str, response: requests.Response, hints: Mapping[str, str] | None = None
) -> ApiError:
    """Build an ApiError from a failed response, using the service's error body when present.

    Graph, Defender, ARM and Key Vault reply ``{"error": {"code", "message"}}``; the Entra
    token endpoint replies ``{"error": "<code>", "error_description": "..."}``. ``hints``
    gives the hint for an error code the API is known to give, before the general ones.
    """
    code: str | None = None
    message: str | None = None
    request_id: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        code = error.get("code") if isinstance(error.get("code"), str) else None
        message = error.get("message") if isinstance(error.get("message"), str) else None
        inner = error.get("innerError")
        if isinstance(inner, dict) and isinstance(inner.get("request-id"), str):
            request_id = inner["request-id"]
    elif isinstance(body, dict) and isinstance(body.get("error"), str):
        code = body["error"]
        description = body.get("error_description")
        if isinstance(description, str) and description.strip():
            # The first line carries the AADSTS code and the reason; the rest is trace ids.
            message = description.strip().splitlines()[0]
    request_id = (
        request_id or response.headers.get("request-id") or response.headers.get("x-ms-request-id")
    )

    status = response.status_code
    detail = _readable(message) if message else ""
    text = f"{name}: HTTP {status}"
    if code:
        text += f" {code}"
    text += f": {detail or response.reason or 'request failed'}"
    if request_id:
        text += f" (request-id {request_id})"
    challenge = response.headers.get("WWW-Authenticate", "").lower()
    if status == 401 and "insufficient_claims" in challenge:
        # Continuous access evaluation: the token was revoked, or a policy changed.
        hint: str | None = (
            "the service revoked the token or wants a sign-in that meets a Conditional "
            "Access policy (a claims challenge); sign in again"
        )
    else:
        hint = (hints or {}).get(code or "") or _hint(status, text.lower())
    return ApiError(text, status=status, code=code, request_id=request_id, hint=hint)


def _readable(message: str) -> str:
    """One readable line from a service error message.

    Some services put a JSON document inside the message (Graph's PIM errors, Intune,
    which nests two deep); those are unwrapped to their inner code and message. Line
    breaks are flattened, and the result is capped so one error cannot flood a terminal.
    """
    codes: list[str] = []
    text = message.strip()
    for _ in range(3):
        if not text.startswith("{"):
            break
        try:
            inner = json.loads(text)
        except ValueError:
            break
        if not isinstance(inner, dict):
            break
        code = inner.get("errorCode") or inner.get("ErrorCode") or inner.get("code")
        if isinstance(code, str) and code:
            codes.append(code)
        found = inner.get("message") or inner.get("Message")
        if not isinstance(found, str):
            text = ""
            break
        text = found.strip()
    flat = " ".join(text.split())
    readable = ": ".join([*codes, flat] if flat else codes)
    return readable if len(readable) <= 400 else readable[:397] + "..."


def _hint(status: int, text: str) -> str | None:
    if status == 403 and "suspended" in text:
        return "the service is suspended in this tenant, usually because its licence or trial ended"
    if status == 403 and "client address is not authorized" in text:
        return "the resource's firewall does not allow this machine's IP address"
    if status in {401, 403} and ("forbidden" in text or "permission" in text):
        return "the token was accepted but lacks the permission this call needs"
    return {
        401: "the API rejected the token; check its audience, tenant and expiry",
        403: "the signed-in identity lacks a role or permission for this call",
    }.get(status)


_DEFAULT_PORTS = {"https": 443, "http": 80}


def _origin(parts: SplitResult) -> tuple[str, str, int | None]:
    """A URL's scheme, host (lower case) and port, the scheme's own port when it names
    none, so ``https://host:443`` and ``https://host`` are the same place."""
    try:
        port = parts.port
    except ValueError:
        port = -1  # a port that cannot be read matches no client's
    return parts.scheme, (parts.hostname or "").lower(), port or _DEFAULT_PORTS.get(parts.scheme)


def _is_local(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_link_local


def _path(url: str) -> str:
    return urlsplit(url).path


class ServiceClient:
    """A client for one service's API, built on an ``ApiClient`` (``self.api``).

    Every service client (Entra, Defender, a Key Vault, ServiceNow's tables, ...) is one:
    close it, or use it in a ``with`` block, to release the HTTP session it made.
    """

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    def close(self) -> None:
        """Close the HTTP session, when this client made it."""
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
