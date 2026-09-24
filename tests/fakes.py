"""Shared fakes. Nothing in the test suite touches the network or a real Azure CLI."""

import base64
import http
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from requests.adapters import BaseAdapter

from libre_devops_helpers.core.auth import AccessToken

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
SUBSCRIPTION = "33333333-3333-3333-3333-333333333333"
OTHER_SUBSCRIPTION = "44444444-4444-4444-4444-444444444444"

# (status, json body) or (status, json body, headers); an Exception is raised instead.
Reply = tuple[int, Any] | tuple[int, Any, dict[str, str]] | Exception
Handler = Callable[[requests.PreparedRequest], Reply]


def make_jwt(claims: dict[str, Any], header: dict[str, Any] | None = None) -> str:
    """An unsigned JWT carrying ``claims``; the signature segment is junk."""

    def segment(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{segment(header or {'alg': 'RS256', 'typ': 'JWT'})}.{segment(claims)}.signature"


def graph_claims(**overrides: Any) -> dict[str, Any]:
    """Claims of a healthy delegated Graph token for TENANT, valid for an hour."""
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "aud": "https://graph.microsoft.com",
        "tid": TENANT,
        "iss": f"https://sts.windows.net/{TENANT}/",
        "upn": "analyst@example.com",
        "appid": "04b07795-8ddb-461a-bbee-02f9e1bf7b46",
        "scp": "Device.Read.All GroupMember.Read.All",
        "iat": now - 60,
        "nbf": now - 60,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


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


class StaticTokens:
    """A TokenProvider handing out a fixed token and recording what was asked for."""

    def __init__(self, token: str = "token-value") -> None:
        self.token = token
        self.calls: list[tuple[str, str]] = []

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        self.calls.append((resource, tenant_id))
        expires = datetime.now(UTC) + timedelta(hours=1)
        return AccessToken(self.token, expires, tenant_id, resource)


class FakeRunner:
    """Stands in for subprocess.run. ``respond(args)`` returns (returncode, stdout, stderr)."""

    def __init__(self, respond: Callable[[list[str]], tuple[int, str, str]]) -> None:
        self.respond = respond
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        args = list(cmd[1:])
        self.calls.append(args)
        self.kwargs.append(kwargs)
        code, out, err = self.respond(args)
        return subprocess.CompletedProcess(cmd, code, out, err)


def account_json(
    subscription: str, tenant: str, *, name: str = "sub", default: bool = False
) -> dict[str, Any]:
    """One entry as ``az account list`` prints it."""
    return {
        "id": subscription,
        "name": name,
        "tenantId": tenant,
        "state": "Enabled",
        "isDefault": default,
        "user": {"name": "analyst@example.com", "type": "user"},
    }


def az_runner(respond: Callable[[list[str]], tuple[int, str, str]]):
    """An AzureCliRunner over a FakeRunner, returned with the fake for its call log."""
    from libre_devops_helpers.microsoft.process import AzureCliRunner

    fake = FakeRunner(respond)
    return AzureCliRunner("az", runner=fake), fake


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


class FakeClock:
    """A monotonic clock that only moves when ``sleep`` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
