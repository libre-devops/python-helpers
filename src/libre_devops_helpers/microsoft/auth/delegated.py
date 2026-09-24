"""Delegated sign-in with your own app registration: a browser, or a device code.

The Azure CLI's delegated token carries scopes Microsoft chose; a public client app
registration you own can be granted others, such as the PIM ones. Two flows:

- ``InteractiveCredential``: the authorisation code flow with PKCE. A browser opens (or
  the URL is shown to open), and the redirect comes back to a one-shot listener on
  127.0.0.1. The ``state`` value is checked, so a stray redirect cannot be accepted.
- ``DeviceCodeCredential``: a code to enter at the device login page, for SSH, WSL or
  anywhere a browser cannot be reached.

The first token needs a sign-in; the refresh token it comes with gets tokens for other
APIs (ARM as well as Graph) without asking again. A ``store`` (``core.token_store``)
keeps that refresh token for the next command: a profile's ``token_cache`` picks it, a
private file unless it says otherwise. Built directly, without a store, a credential
keeps it in memory for its own lifetime only. Access tokens are never kept, and nothing
is ever logged.

On a machine with no browser to open, the browser flow signs in with a device code
instead, as the Azure CLI does.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import logging
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import requests

from libre_devops_helpers.core.auth import AccessToken, utc_now
from libre_devops_helpers.core.browser import can_launch_browser
from libre_devops_helpers.core.errors import ApiError, AuthError, LdoError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.token_store import MemoryStore, TokenStore
from libre_devops_helpers.microsoft.auth.entra import parse_token_response, scope_for
from libre_devops_helpers.microsoft.auth.lapse import lapse_reason
from libre_devops_helpers.microsoft.clouds import PUBLIC

log = logging.getLogger(__name__)

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SIGN_IN_TIMEOUT = 300.0
SIGNED_IN_PAGE = b"<h1>Signed in</h1><p>You can close this tab and go back to the terminal.</p>"


def _notify_by_log(message: str) -> None:
    log.warning("%s", message)


class _DelegatedCredential:
    """What both flows share: the token endpoint, and a refresh token per tenant."""

    def __init__(
        self,
        client_id: str,
        *,
        login_url: str,
        session: requests.Session | None,
        verify: bool | str,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
        notify: Callable[[str], None] | None,
        store: TokenStore | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client_id = client_id
        self.login_url = login_url.rstrip("/")
        self._endpoint = ApiClient(
            login_url, None, name="Entra ID sign-in", session=session, verify=verify, sleep=sleep
        )
        self._clock = clock
        self._sleep = sleep
        self._notify = notify or _notify_by_log
        self._store = store or MemoryStore()
        self._monotonic = monotonic
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(client_id={self.client_id!r})"

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        with self._lock:
            refresh = self._recall(tenant_id)
            if refresh:
                try:
                    return self._redeem(
                        tenant_id,
                        resource,
                        {"grant_type": "refresh_token", "refresh_token": refresh},
                    )
                except AuthError as exc:
                    # Revoked or expired: sign in again rather than fail the command.
                    self._forget(tenant_id)
                    reason = lapse_reason(str(exc)) or "the refresh token was refused"
                    self._notify(f"Signing in again: {reason}.")
            return self._sign_in(resource, tenant_id)

    def sign_out(self, tenant_id: str) -> bool:
        """Forget the kept sign-in for ``tenant_id``. True when there was one."""
        with self._lock:
            return self._store.delete(self._key(tenant_id))

    def _key(self, tenant_id: str) -> str:
        # One sign-in per cloud, app and tenant.
        return f"{urlsplit(self.login_url).netloc}|{self.client_id}|{tenant_id.lower()}"

    def _recall(self, tenant_id: str) -> str | None:
        try:
            return self._store.load(self._key(tenant_id))
        except LdoError as exc:
            self._notify(f"The kept sign-in cannot be used ({exc}); signing in afresh.")
            return None

    def _remember(self, tenant_id: str, refresh: str) -> None:
        try:
            self._store.save(self._key(tenant_id), refresh)
        except LdoError as exc:
            # The token works for this command all the same.
            self._notify(f"The sign-in could not be kept for the next command: {exc}")

    def _forget(self, tenant_id: str) -> None:
        try:
            self._store.delete(self._key(tenant_id))
        except LdoError as exc:
            log.warning("could not forget a refused refresh token: %s", exc)

    def _sign_in(self, resource: str, tenant_id: str) -> AccessToken:
        raise NotImplementedError

    def _sign_in_with_device_code(self, resource: str, tenant_id: str) -> AccessToken:
        """The device code flow: a code to enter at the device login page, then a poll."""
        try:
            flow = self._post(tenant_id, "devicecode", {"scope": self._scope(resource)})
        except ApiError as exc:
            raise AuthError(str(exc), hint=_hint(exc)) from None
        device_code = str(flow.get("device_code") or "")
        if not device_code:
            raise AuthError("the device code response has no device_code")
        self._notify(
            str(
                flow.get("message")
                or f"Enter {flow.get('user_code')} at {flow.get('verification_uri')}"
            )
        )
        interval = float(flow.get("interval") or 5)
        deadline = self._monotonic() + float(flow.get("expires_in") or 900)
        form = {"grant_type": DEVICE_CODE_GRANT, "device_code": device_code}
        while self._monotonic() < deadline:
            self._sleep(interval)
            now = self._clock()
            try:
                data = self._post(tenant_id, "token", {**form, "scope": self._scope(resource)})
            except ApiError as exc:
                if exc.code == "authorization_pending":
                    continue
                if exc.code == "slow_down":
                    interval += 5
                    continue
                raise AuthError(str(exc), hint=_hint(exc)) from None
            return self._keep(data, resource, tenant_id, now)
        raise AuthError("the device code expired before sign-in completed; start again")

    def _scope(self, resource: str) -> str:
        return f"{scope_for(resource)} offline_access"

    def _post(self, tenant_id: str, path: str, form: Mapping[str, str]) -> dict[str, Any]:
        return self._endpoint.request(
            "POST", f"/{tenant_id}/oauth2/v2.0/{path}", form={"client_id": self.client_id, **form}
        )

    def _redeem(self, tenant_id: str, resource: str, form: Mapping[str, str]) -> AccessToken:
        now = self._clock()
        try:
            data = self._post(tenant_id, "token", {**form, "scope": self._scope(resource)})
        except ApiError as exc:
            raise AuthError(str(exc), hint=_hint(exc)) from None
        return self._keep(data, resource, tenant_id, now)

    def _keep(
        self, data: Mapping[str, Any], resource: str, tenant_id: str, now: datetime
    ) -> AccessToken:
        refresh = data.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            self._remember(tenant_id, refresh)
        return parse_token_response(data, resource, tenant_id, now=now, name="Entra ID sign-in")


class CodeReceiver(Protocol):
    """Where the browser's redirect lands. ``wait`` returns its query parameters."""

    redirect_uri: str

    def wait(self, timeout: float) -> dict[str, str]:
        """The redirect's query parameters, once it arrives within ``timeout`` seconds."""

    def close(self) -> None:
        """Stop listening."""


class LoopbackReceiver:
    """A one-shot HTTP listener on 127.0.0.1 for the sign-in redirect."""

    def __init__(self, port: int = 0) -> None:
        received: dict[str, str] = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
                if "code" in query or "error" in query:
                    received.update(query)
                    body = SIGNED_IN_PAGE
                    self.send_response(200)
                else:
                    body = b"Not found"
                    self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                # The query holds the authorisation code, so the request line is never logged.
                return

        self._received = received
        self._server = http.server.HTTPServer(("127.0.0.1", port), Handler)
        self._server.timeout = 0.5
        self.redirect_uri = f"http://localhost:{self._server.server_address[1]}"

    def wait(self, timeout: float) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while not self._received and time.monotonic() < deadline:
            self._server.handle_request()
        if not self._received:
            raise AuthError(f"no sign-in completed within {int(timeout)}s")
        return dict(self._received)

    def close(self) -> None:
        self._server.server_close()


class InteractiveCredential(_DelegatedCredential):
    """Delegated tokens from a browser sign-in (authorisation code with PKCE)."""

    def __init__(
        self,
        client_id: str,
        *,
        login_url: str = PUBLIC.login_url,
        session: requests.Session | None = None,
        verify: bool | str = True,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        notify: Callable[[str], None] | None = None,
        store: TokenStore | None = None,
        open_browser: Callable[[str], object] = webbrowser.open,
        receiver: Callable[[], CodeReceiver] = LoopbackReceiver,
        timeout: float = SIGN_IN_TIMEOUT,
        has_browser: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            client_id,
            login_url=login_url,
            session=session,
            verify=verify,
            clock=clock,
            sleep=sleep,
            notify=notify,
            store=store,
            monotonic=monotonic,
        )
        self._open_browser = open_browser
        self._receiver = receiver
        self._timeout = timeout
        self._has_browser = has_browser or can_launch_browser

    def _sign_in(self, resource: str, tenant_id: str) -> AccessToken:
        if not self._has_browser():
            # Headless: the browser's redirect could never reach this machine's listener.
            self._notify("No web browser here, so signing in with a device code instead.")
            return self._sign_in_with_device_code(resource, tenant_id)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(24)
        receiver = self._receiver()
        try:
            params = {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": receiver.redirect_uri,
                "response_mode": "query",
                "scope": self._scope(resource),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "prompt": "select_account",
            }
            url = f"{self.login_url}/{quote(tenant_id)}/oauth2/v2.0/authorize?" + urlencode(
                params, quote_via=quote
            )
            self._notify(f"Sign in to continue (opening your browser): {url}")
            try:
                self._open_browser(url)
            except Exception:
                log.debug("could not open a browser", exc_info=True)
            query = receiver.wait(self._timeout)
        finally:
            receiver.close()
        if query.get("state") != state:
            raise AuthError("the sign-in response did not match this request; start again")
        if "error" in query:
            detail = query.get("error_description") or query["error"]
            raise AuthError(f"sign-in failed: {detail.splitlines()[0]}", hint=_hint_text(detail))
        code = query.get("code")
        if not code:
            raise AuthError("the sign-in response carried no authorisation code")
        return self._redeem(
            tenant_id,
            resource,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": receiver.redirect_uri,
                "code_verifier": verifier,
            },
        )


class DeviceCodeCredential(_DelegatedCredential):
    """Delegated tokens from a device code entered at the device login page."""

    def __init__(
        self,
        client_id: str,
        *,
        login_url: str = PUBLIC.login_url,
        session: requests.Session | None = None,
        verify: bool | str = True,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        notify: Callable[[str], None] | None = None,
        store: TokenStore | None = None,
    ) -> None:
        super().__init__(
            client_id,
            login_url=login_url,
            session=session,
            verify=verify,
            clock=clock,
            sleep=sleep,
            notify=notify,
            store=store,
            monotonic=monotonic,
        )

    def _sign_in(self, resource: str, tenant_id: str) -> AccessToken:
        return self._sign_in_with_device_code(resource, tenant_id)


def _hint(exc: ApiError) -> str | None:
    return _hint_text(str(exc))


def _hint_text(text: str) -> str | None:
    if "AADSTS65001" in text or "consent" in text.lower():
        return "the app needs consent for these permissions; an admin can grant it in Entra ID"
    if "AADSTS700016" in text:
        return "no app with this client_id exists in the tenant; check the profile's client_id"
    if "AADSTS7000218" in text:
        return "the app must allow public client flows (Authentication > Allow public client flows)"
    if "AADSTS50011" in text:
        return "add http://localhost as a 'Mobile and desktop' redirect URI on the app"
    if "AADSTS70043" in text or "AADSTS700082" in text or "invalid_grant" in text:
        return "the sign-in expired; run the command again to sign in"
    return None
