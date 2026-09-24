"""Signing in to a ServiceNow instance as yourself: OAuth with a kept sign-in, or basic.

``OAuthCredential`` signs in through an OAuth application registry entry on the
instance (its client id and secret), and keeps the refresh token it gets, so later
commands sign in by themselves until it expires (100 days by default) or is revoked:

- ``browser``: the authorisation code flow with PKCE. You open a link in any browser and
  sign in as you would to the instance (single sign-on and MFA included), then paste
  back the address the browser lands on. Nothing has to listen there, so this works on
  a headless machine, and at a workplace that will not allow passwords on the API.
- ``password``: the username and password, once, for the tokens.

``BasicCredential`` sends the username and password with every request. ServiceNow now
refuses that for ordinary interactive accounts unless they hold the
``snc_basic_auth_api_access`` role.

Access tokens are never kept. A client secret typed in at sign-in (rather than set in
the environment) is kept with the refresh token, so it is not asked for again. Nothing
is logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import requests

from libre_devops_helpers.core.auth import AccessToken, utc_now
from libre_devops_helpers.core.browser import can_launch_browser
from libre_devops_helpers.core.errors import ApiError, AuthError, LdoError, ReauthRequired
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.token_store import MemoryStore, TokenStore, open_store
from libre_devops_helpers.servicenow.config import (
    CLIENT_ID_ENV,
    USERNAME_ENV,
    Profile,
)

log = logging.getLogger(__name__)

# (question, hide the answer) -> the answer. The CLI asks on a terminal; without one,
# nothing is asked and a missing sign-in is an error saying how to sign in.
Ask = Callable[[str, bool], str]
DEFAULT_ACCESS_LIFETIME = 1800.0  # ServiceNow's default: 30 minutes


class BasicCredential:
    """Your username and password, sent with each request (HTTP Basic)."""

    scheme = "Basic"

    def __init__(self, username: str, password: str) -> None:
        if not username:
            raise AuthError("basic sign-in needs a username")
        if not password:
            raise AuthError("basic sign-in needs a password")
        self.username = username
        self._encoded = base64.b64encode(f"{username}:{password}".encode()).decode()

    def __repr__(self) -> str:
        return f"BasicCredential(username={self.username!r})"

    def authorization(self) -> str:
        """The value that follows ``Basic`` in the Authorization header."""
        return self._encoded


@dataclass(frozen=True)
class OAuthApp:
    """The OAuth application registry entry: where to sign in, and as which client."""

    instance: str
    client_id: str
    client_secret: str | None  # None: from the kept sign-in, or asked for
    redirect_uri: str


class OAuthCredential:
    """OAuth 2.0 against the instance itself, with the sign-in kept in ``store``.

    It satisfies ``core.auth.TokenProvider`` (``resource`` and ``tenant_id`` are not
    needed: one credential is one instance and one account), so ``CachingTokenProvider``
    and ``BearerToken`` work as they do for Entra ID.
    """

    def __init__(
        self,
        app: OAuthApp,
        *,
        key: str,
        sign_in: str = "browser",
        username: str | None = None,
        password: Callable[[], str | None] = lambda: None,
        ask: Ask | None = None,
        store: TokenStore | None = None,
        session: requests.Session | None = None,
        verify: bool | str = True,
        clock: Callable[[], datetime] = utc_now,
        notify: Callable[[str], None] | None = None,
        open_browser: Callable[[str], object] = webbrowser.open,
        has_browser: Callable[[], bool] = can_launch_browser,
        sign_in_hint: str = "sign in again",
    ) -> None:
        if not app.client_id:
            raise AuthError("OAuth sign-in needs the application's client id")
        if sign_in == "password" and not username:
            raise AuthError('sign_in = "password" needs a username')
        self.app = app
        self.key = key
        self.sign_in_method = sign_in
        self.username = username
        self._password = password
        self._ask = ask
        self._store = store or MemoryStore()
        self._clock = clock
        self._notify = notify or (lambda message: log.warning("%s", message))
        self._open_browser = open_browser
        self._has_browser = has_browser
        self._sign_in_hint = sign_in_hint
        self._endpoint = ApiClient(
            app.instance, None, name="ServiceNow sign-in", session=session, verify=verify
        )
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"OAuthCredential(instance={self.app.instance!r}, "
            f"client_id={self.app.client_id!r}, sign_in={self.sign_in_method!r})"
        )

    def get_token(self, resource: str = "", tenant_id: str = "") -> AccessToken:
        with self._lock:
            kept = self._recall()
            refresh = kept.get("refresh_token")
            if refresh:
                try:
                    return self._grant(
                        {"grant_type": "refresh_token", "refresh_token": refresh}, kept
                    )
                except AuthError:
                    self._forget()
                    self._notify("The kept ServiceNow sign-in was refused; signing in again.")
            return self._sign_in(kept)

    def sign_in(self) -> AccessToken:
        """Sign in afresh, ignoring any kept sign-in, and keep the new one."""
        with self._lock:
            kept = self._recall()
            kept.pop("refresh_token", None)
            return self._sign_in(kept)

    def sign_out(self) -> bool:
        """Forget the kept sign-in. True when there was one."""
        with self._lock:
            return self._store.delete(self.key)

    def has_kept_sign_in(self) -> bool:
        try:
            return bool(self._decode(self._store.load(self.key)).get("refresh_token"))
        except LdoError:
            return False

    # Signing in ----------------------------------------------------------------------

    def _sign_in(self, kept: dict[str, str]) -> AccessToken:
        if self.sign_in_method == "password":
            password = self._password()
            if not password and self._ask is not None:
                password = self._ask(f"ServiceNow password for {self.username}", True)
            if not password:
                raise self._needs_sign_in("no password to sign in with")
            form = {"grant_type": "password", "username": self.username or "", "password": password}
            return self._grant(form, kept)
        if self._ask is None:
            raise self._needs_sign_in("signing in needs a browser and someone to paste back")
        return self._browser_sign_in(kept)

    def _browser_sign_in(self, kept: dict[str, str]) -> AccessToken:
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": self.app.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self.app.instance}/oauth_auth.do?" + urlencode(params, quote_via=quote)
        self._notify(
            "Open this link in a browser and sign in to ServiceNow. You will land on an "
            f"address starting {self.app.redirect_uri} (the page may not load: that is "
            f"fine). Copy that whole address and paste it here.\n\n{url}\n"
        )
        if self._has_browser():
            try:
                self._open_browser(url)
            except Exception:
                log.debug("could not open a browser", exc_info=True)
        assert self._ask is not None
        pasted = self._ask("The address you landed on", False).strip()
        query = {key: values[0] for key, values in parse_qs(urlsplit(pasted).query).items()}
        if "error" in query:
            detail = query.get("error_description") or query["error"]
            raise AuthError(f"ServiceNow sign-in failed: {detail}")
        if query.get("state") != state:
            raise AuthError(
                "that address is not from this sign-in (its state does not match)",
                hint="paste the whole address the browser landed on, from this sign-in",
            )
        code = query.get("code")
        if not code:
            raise AuthError("that address carries no authorisation code")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.app.redirect_uri,
            "code_verifier": verifier,
        }
        return self._grant(form, kept)

    def _needs_sign_in(self, why: str) -> ReauthRequired:
        return ReauthRequired(
            f"there is no kept sign-in to {self.app.instance}, and {why}",
            hint=self._sign_in_hint,
            reason="no kept sign-in",
        )

    # The token endpoint --------------------------------------------------------------

    def _grant(self, form: Mapping[str, str], kept: dict[str, str]) -> AccessToken:
        secret, typed = self._client_secret(kept)
        now = self._clock()
        try:
            data = self._endpoint.request(
                "POST",
                "/oauth_token.do",
                form={"client_id": self.app.client_id, "client_secret": secret, **form},
            )
        except ApiError as exc:
            raise AuthError(str(exc), hint=_hint(exc)) from None
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError("the ServiceNow token response has no access_token")
        refresh = data.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            record = {"refresh_token": refresh}
            if typed or ("client_secret" in kept and self.app.client_secret is None):
                record["client_secret"] = secret
            self._remember(record)
        lifetime = _number(data.get("expires_in")) or DEFAULT_ACCESS_LIFETIME
        return AccessToken(
            token=token,
            expires_on=now + timedelta(seconds=lifetime),
            tenant_id=self.username or "",
            resource=self.app.instance,
        )

    def _client_secret(self, kept: Mapping[str, str]) -> tuple[str, bool]:
        """The client secret, and whether it was typed in just now (so worth keeping)."""
        if self.app.client_secret:
            return self.app.client_secret, False
        if kept.get("client_secret"):
            return kept["client_secret"], False
        if self._ask is not None:
            typed = self._ask("Client secret of the OAuth application", True).strip()
            if typed:
                return typed, True
        raise self._needs_sign_in("no client secret")

    # The kept sign-in ----------------------------------------------------------------

    def _recall(self) -> dict[str, str]:
        try:
            return self._decode(self._store.load(self.key))
        except LdoError as exc:
            self._notify(f"The kept ServiceNow sign-in cannot be used ({exc}); signing in afresh.")
            return {}

    def _remember(self, record: Mapping[str, str]) -> None:
        try:
            self._store.save(self.key, json.dumps(dict(record), sort_keys=True))
        except LdoError as exc:
            self._notify(f"The ServiceNow sign-in could not be kept for the next command: {exc}")

    def _forget(self) -> None:
        try:
            self._store.delete(self.key)
        except LdoError as exc:
            log.warning("could not forget a refused ServiceNow sign-in: %s", exc)

    @staticmethod
    def _decode(value: str | None) -> dict[str, str]:
        if not value:
            return {}
        try:
            data = json.loads(value)
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: item for key, item in data.items() if isinstance(item, str) and item}


Credential = BasicCredential | OAuthCredential


def credential_for(
    profile: Profile,
    *,
    environ: Mapping[str, str] = os.environ,
    store: TokenStore | None = None,
    ask: Ask | None = None,
    session: requests.Session | None = None,
    verify: bool | str = True,
    notify: Callable[[str], None] | None = None,
    sign_in_hint: str = "sign in again",
    has_browser: Callable[[], bool] = can_launch_browser,
    open_browser: Callable[[str], object] = webbrowser.open,
) -> Credential:
    """The credential ``profile`` describes, with its secrets from ``environ`` (or asked)."""
    username = profile.username or environ.get(USERNAME_ENV, "").strip() or None
    if profile.auth == "basic":
        password = environ.get(profile.password_env, "")
        if not username:
            raise AuthError(
                f"ServiceNow profile {profile.name!r} has no username",
                hint=f"set username on the profile, or {USERNAME_ENV}",
            )
        if not password:
            raise AuthError(
                f"ServiceNow profile {profile.name!r} needs a password",
                hint=f"set {profile.password_env}; the config file never holds passwords",
            )
        return BasicCredential(username, password)
    client_id = profile.client_id or environ.get(CLIENT_ID_ENV, "").strip()
    if not client_id:
        raise AuthError(
            f"ServiceNow profile {profile.name!r} has no OAuth client id",
            hint=(
                f"set client_id on the profile, or {CLIENT_ID_ENV}: the client id of an "
                "entry in System OAuth > Application Registry"
            ),
        )
    if profile.sign_in == "password" and not username:
        raise AuthError(
            f"ServiceNow profile {profile.name!r} signs in with a password but has no username",
            hint=f"set username on the profile, or {USERNAME_ENV}",
        )
    return OAuthCredential(
        OAuthApp(
            instance=profile.instance,
            client_id=client_id,
            client_secret=environ.get(profile.client_secret_env) or None,
            redirect_uri=profile.redirect_uri,
        ),
        key=f"servicenow|{profile.host}|{client_id}|{profile.name}",
        sign_in=profile.sign_in,
        username=username,
        password=lambda: environ.get(profile.password_env) or None,
        ask=ask,
        store=store or open_store(profile.token_cache, environ=environ),
        session=session,
        verify=verify,
        notify=notify,
        sign_in_hint=sign_in_hint,
        has_browser=has_browser,
        open_browser=open_browser,
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip().isdigit():
        return float(value)
    return None


def _hint(exc: ApiError) -> str:
    text = str(exc).lower()
    if "invalid_client" in text:
        return "check the client id and secret against the application registry entry"
    if "invalid_grant" in text or "access_denied" in text:
        return (
            "the instance refused the sign-in: check the username and password (or sign in "
            "again), and that the application registry entry is active; repeated failures "
            "lock the account for a while"
        )
    return "check the application registry entry is active, and its client id and secret"
