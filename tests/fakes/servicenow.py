"""A fake ServiceNow instance: the Table API over a few tables, and its OAuth endpoints.

It checks sign-ins as the real one does (basic, or a bearer token it issued), answers
the encoded queries the tool sends, and runs the password, refresh token and
authorisation code (with PKCE) grants. ``approve`` plays the person in the browser.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from fakes.http import form_body

INSTANCE = "https://dev12345.service-now.com"
USERNAME = "ana"
PASSWORD = "p4ss-word"
CLIENT_ID = "0123456789abcdef0123456789abcdef"
CLIENT_SECRET = "snow-client-secret"
REDIRECT = "http://localhost:8765/callback"
USER_ID = "6816f79cc0a8016401c5a33be04be441"
BUILD_TAG = "glide-yokohama-12-18-2024__patch4-06-25-2025"
WAR = "glide-zurich-07-01-2025__patch10-05-22-2026_06-12-2026_2311.zip"
# Tables the real instance closes to the REST API, even to admin.
CLOSED = {"v_plugin", "sys_plugins", "sys_store_app", "sys_package"}


def user_record(**overrides) -> dict:
    record = {
        "sys_id": USER_ID,
        "user_name": USERNAME,
        "name": "Ana Analyst",
        "email": "ana@example.com",
        "active": "true",
        "locked_out": "false",
        "web_service_access_only": "false",
        "last_login_time": "2026-09-24 08:00:00",
    }
    record.update(overrides)
    return record


class FakeInstance:
    """Replies for every call the ServiceNow commands make, from in-memory tables."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {
            "sys_user": [user_record()],
            "sys_user_has_role": [
                {"user": USER_ID, "state": "active", "role.name": "itil"},
                {"user": USER_ID, "state": "active", "role.name": "admin"},
                {"user": USER_ID, "state": "inactive", "role.name": "old_role"},
            ],
            # Zurich keeps the build in glide.war, not glide.buildtag.last.
            "sys_properties": [{"name": "glide.war", "value": WAR}],
            "sys_scope": [
                {
                    "scope": "sn_vul",
                    "name": "Vulnerability Response",
                    "active": "true",
                    "version": "18.0",
                    "sys_class_name": "sys_store_app",
                },
                {
                    "scope": "x_acme_tools",
                    "name": "Acme tools",
                    "active": "false",
                    "version": "1.0.0",
                    "sys_class_name": "sys_app",
                },
            ],
            "sys_db_object": [{"name": "incident"}, {"name": "sys_user"}],
        }
        self.basic_allowed = True
        self.hibernating = False
        self.denied: set[str] = set()
        self.access: set[str] = set()
        self.refresh: set[str] = set()
        self.codes: dict[str, tuple[str, str]] = {}  # code -> (challenge, redirect)
        self.requests: list = []
        self.grants: list[str] = []

    # The person in the browser -----------------------------------------------------

    def approve(self, authorize_url: str, *, deny: bool = False) -> str:
        """Sign in at ``authorize_url``; return the address the browser lands on."""
        query = {key: values[0] for key, values in parse_qs(urlsplit(authorize_url).query).items()}
        assert urlsplit(authorize_url).path == "/oauth_auth.do"
        assert query["client_id"] == CLIENT_ID
        assert query["code_challenge_method"] == "S256"
        if deny:
            params = {"error": "access_denied", "state": query["state"]}
        else:
            code = secrets.token_urlsafe(12)
            self.codes[code] = (query["code_challenge"], query["redirect_uri"])
            params = {"code": code, "state": query["state"]}
        return f"{query['redirect_uri']}?{urlencode(params)}"

    # Requests ------------------------------------------------------------------------

    def __call__(self, request):
        self.requests.append(request)
        if self.hibernating:
            page = b"<html><body>Your instance is hibernating</body></html>"
            return (200, page, {"Content-Type": "text/html"})
        parts = urlsplit(request.url)
        if parts.path == "/oauth_token.do":
            return self._token(form_body(request))
        if parts.path.startswith("/api/now/table/"):
            return self._table(request, parts.path.removeprefix("/api/now/table/"), parts.query)
        raise AssertionError(f"unexpected request {request.url}")

    def _authenticated(self, request) -> bool:
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            expected = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
            return self.basic_allowed and header == f"Basic {expected}"
        return header.startswith("Bearer ") and header.removeprefix("Bearer ") in self.access

    def _table(self, request, name: str, raw_query: str):
        if not self._authenticated(request):
            body = {
                "error": {
                    "message": "User is not authenticated",
                    "detail": "Required to provide Auth information",
                },
                "status": "failure",
            }
            return (401, body, {"WWW-Authenticate": 'Basic realm="Service-now"'})
        if name in self.denied or name in CLOSED:
            detail = "Failed API level ACL Validation"
            error = {"message": "User Not Authorized", "detail": detail}
            return (403, {"error": error, "status": "failure"}, {})
        if name not in self.tables:
            body = {"error": {"message": f"Invalid table {name}"}, "status": "failure"}
            return (400, body, {})
        params = {key: values[0] for key, values in parse_qs(raw_query).items()}
        rows = [row for row in self.tables[name] if _matches(row, params.get("sysparm_query", ""))]
        offset = int(params.get("sysparm_offset", "0"))
        limit = int(params.get("sysparm_limit", "10000"))
        page = rows[offset : offset + limit]
        fields = params.get("sysparm_fields")
        if fields:
            wanted = fields.split(",")
            page = [{key: row[key] for key in wanted if key in row} for row in page]
        return (200, {"result": page}, {"X-Total-Count": str(len(rows))})

    def _token(self, form: dict[str, str]):
        grant = form.get("grant_type", "")
        self.grants.append(grant)
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return (401, {"error": "invalid_client", "error_description": "invalid_client"})
        if grant == "password":
            if form.get("username") != USERNAME or form.get("password") != PASSWORD:
                return (401, {"error": "access_denied", "error_description": "access_denied"})
        elif grant == "refresh_token":
            if form.get("refresh_token") not in self.refresh:
                return (401, {"error": "invalid_grant", "error_description": "invalid_grant"})
        elif grant == "authorization_code":
            challenge, redirect = self.codes.pop(form.get("code", ""), ("", ""))
            verifier = form.get("code_verifier", "")
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            if (
                not challenge
                or digest.rstrip(b"=").decode() != challenge
                or form.get("redirect_uri") != redirect
            ):
                return (401, {"error": "invalid_grant", "error_description": "invalid_grant"})
        else:
            return (400, {"error": "unsupported_grant_type"})
        access = f"access-{secrets.token_hex(4)}"
        refresh = f"refresh-{secrets.token_hex(4)}"
        self.access.add(access)
        self.refresh.add(refresh)
        return (
            200,
            {
                "access_token": access,
                "refresh_token": refresh,
                "scope": "useraccount",
                "token_type": "Bearer",
                "expires_in": 1799,
            },
        )


def _matches(row: dict, query: str) -> bool:
    """A little of ServiceNow's encoded query language: =, LIKE, ^ (and) and ^OR (or)."""
    if not query:
        return True
    groups: list[list[str]] = []
    for term in query.split("^"):
        if term.startswith("OR") and groups:
            groups[-1].append(term[2:])
        else:
            groups.append([term])
    return all(any(_term(row, term) for term in group) for group in groups)


def _term(row: dict, term: str) -> bool:
    field, _, values = term.partition("IN")
    if values and "=" not in field:
        return str(row.get(field, "")) in values.split(",")
    if "LIKE" in term:
        field, value = term.split("LIKE", 1)
        return value.casefold() in str(row.get(field, "")).casefold()
    field, value = term.split("=", 1)
    if value == "javascript:gs.getUserID()":
        value = USER_ID
    return str(row.get(field, "")) == value


def run(args, instance, *, environ=None, config=None, ask=None, store=None, notify=None):
    """Run an ``ldo snow`` command against ``instance``, as a terminal when ``ask`` is given.

    ``notify`` receives what the command shows while signing in (the browser link).
    """
    from typer.testing import CliRunner

    from fakes.http import fake_session
    from libre_devops_helpers.cli import app
    from libre_devops_helpers.cli.runtime import Runtime
    from libre_devops_helpers.core.token_store import MemoryStore

    obj = Runtime(
        config_path=config,
        session=fake_session(instance)[0],
        environ=environ if environ is not None else {},
        token_store=store if store is not None else MemoryStore(),
    )
    obj.has_browser = lambda: False
    obj.open_browser = lambda url: None
    if notify is not None:
        obj.notify = notify
    if ask is not None:
        obj.interactive = lambda: True
        obj.ask = ask
    else:
        obj.interactive = lambda: False
    return CliRunner().invoke(app, args, obj=obj)
