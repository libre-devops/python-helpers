"""A fake requests adapter: routes requests to a handler and records each one."""

import http
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlsplit

import requests
from requests.adapters import BaseAdapter

# (status, json body) or (status, json body, headers); an Exception is raised instead.
Reply = tuple[int, Any] | tuple[int, Any, dict[str, str]] | Exception

Handler = Callable[[requests.PreparedRequest], Reply]


class FakeAdapter(BaseAdapter):
    """Routes requests to ``handler`` instead of the network and records each one."""

    def __init__(self, handler: Handler) -> None:
        super().__init__()
        self.handler = handler
        self.requests: list[requests.PreparedRequest] = []

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.requests.append(request)
        reply = self.handler(request)
        if isinstance(reply, Exception):
            raise reply
        status, body, *rest = reply
        response = requests.Response()
        response.status_code = status
        response.reason = http.HTTPStatus(status).phrase
        response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        response.headers.update({"Content-Type": "application/json", **(rest[0] if rest else {})})
        response.url = request.url
        response.request = request
        response.encoding = "utf-8"
        return response

    def close(self) -> None:
        pass


def fake_session(handler: Handler) -> tuple[requests.Session, FakeAdapter]:
    """A requests session whose https traffic goes to ``handler``."""
    session = requests.Session()
    adapter = FakeAdapter(handler)
    session.mount("https://", adapter)
    return session, adapter


def json_body(request: requests.PreparedRequest) -> Any:
    """The JSON a request sent."""
    body = request.body
    return json.loads(body.decode() if isinstance(body, bytes) else body or "null")


def form_body(request: requests.PreparedRequest) -> dict[str, str]:
    """The form fields a request sent (one value each)."""
    from urllib.parse import parse_qs

    body = request.body
    text = body.decode() if isinstance(body, bytes) else body or ""
    return {key: values[0] for key, values in parse_qs(text).items()}


Route = Reply | Callable[[requests.PreparedRequest], Reply]


def routes(table: dict[str, Route]) -> Handler:
    """A handler that answers by URL path, for tests that need a few endpoints.

    ``{"/v1.0/users/ana@example.com": (200, {...})}`` answers that path; a key ending in
    ``*`` answers every path it begins; a value may be a function of the request. Any
    other request fails the test, so a command cannot quietly call something new.
    """

    def handler(request: requests.PreparedRequest) -> Reply:
        path = urlsplit(request.url or "").path
        for pattern, reply in table.items():
            if path == pattern or (pattern.endswith("*") and path.startswith(pattern[:-1])):
                return reply(request) if callable(reply) else reply
        raise AssertionError(f"unexpected request {unquote(request.url or '')}")

    return handler
