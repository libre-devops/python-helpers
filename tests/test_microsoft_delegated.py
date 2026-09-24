import base64
import hashlib
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes import TENANT, FakeClock, fake_session, form_body
from libre_devops_helpers.core.errors import AuthError
from libre_devops_helpers.microsoft.auth import (
    DeviceCodeCredential,
    InteractiveCredential,
    LoopbackReceiver,
    credential_for,
)
from libre_devops_helpers.microsoft.config import Profile

CLIENT_ID = "77777777-7777-7777-7777-777777777777"
GRAPH = "https://graph.microsoft.com"
ARM = "https://management.azure.com/"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def token_reply(name: str) -> tuple[int, dict]:
    return (200, {"access_token": name, "expires_in": 3600, "refresh_token": f"refresh-{name}"})


class Browser:
    """Stands in for the browser and the redirect: it answers the URL it is shown."""

    def __init__(self, *, error: str | None = None, state: str | None = None) -> None:
        self.urls: list[str] = []
        self.error = error
        self.state = state

    def open(self, url: str) -> None:
        self.urls.append(url)

    def receiver(self) -> "FakeReceiver":
        return FakeReceiver(self)


class FakeReceiver:
    redirect_uri = "http://localhost:50123"

    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        self.closed = False

    def wait(self, timeout: float) -> dict[str, str]:
        sent = parse_qs(urlsplit(self.browser.urls[-1]).query)
        state = self.browser.state or sent["state"][0]
        if self.browser.error:
            return {
                "error": "access_denied",
                "error_description": self.browser.error,
                "state": state,
            }
        return {"code": "auth-code", "state": state}

    def close(self) -> None:
        self.closed = True


def interactive(handler, browser: Browser, notices: list[str] | None = None):
    session, adapter = fake_session(handler)
    credential = InteractiveCredential(
        CLIENT_ID,
        session=session,
        clock=lambda: NOW,
        open_browser=browser.open,
        receiver=browser.receiver,
        notify=(notices if notices is not None else []).append,
    )
    return credential, adapter


def test_the_browser_flow_uses_pkce_and_checks_the_state():
    browser = Browser()
    notices: list[str] = []
    credential, adapter = interactive(lambda request: token_reply("graph-token"), browser, notices)
    token = credential.get_token(GRAPH, TENANT)
    assert token.token == "graph-token"
    authorize = parse_qs(urlsplit(browser.urls[0]).query)
    assert urlsplit(browser.urls[0]).path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert authorize["code_challenge_method"] == ["S256"]
    assert authorize["scope"] == [f"{GRAPH}/.default offline_access"]
    assert authorize["redirect_uri"] == [FakeReceiver.redirect_uri]
    exchange = form_body(adapter.requests[0])
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code"] == "auth-code"
    # The verifier sent to the token endpoint must hash to the challenge shown to Entra.
    digest = hashlib.sha256(exchange["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == authorize["code_challenge"][0]
    assert any(browser.urls[0] in notice for notice in notices)


def test_a_second_api_is_reached_with_the_refresh_token_not_another_sign_in():
    replies = iter([token_reply("graph-token"), token_reply("arm-token")])
    browser = Browser()
    credential, adapter = interactive(lambda request: next(replies), browser)
    credential.get_token(GRAPH, TENANT)
    assert credential.get_token(ARM, TENANT).token == "arm-token"
    assert len(browser.urls) == 1
    refresh = form_body(adapter.requests[1])
    assert (refresh["grant_type"], refresh["refresh_token"]) == (
        "refresh_token",
        "refresh-graph-token",
    )
    assert refresh["scope"] == "https://management.azure.com/.default offline_access"


def test_a_rejected_refresh_token_falls_back_to_signing_in_again():
    replies = iter(
        [
            token_reply("first"),
            (400, {"error": "invalid_grant", "error_description": "AADSTS70043: expired"}),
            token_reply("second"),
        ]
    )
    browser = Browser()
    credential, _ = interactive(lambda request: next(replies), browser)
    credential.get_token(GRAPH, TENANT)
    assert credential.get_token(ARM, TENANT).token == "second"
    assert len(browser.urls) == 2


def test_a_response_with_the_wrong_state_is_refused():
    credential, adapter = interactive(lambda request: token_reply("x"), Browser(state="forged"))
    with pytest.raises(AuthError, match="did not match"):
        credential.get_token(GRAPH, TENANT)
    assert adapter.requests == []


def test_a_sign_in_error_is_reported_with_a_hint():
    browser = Browser(error="AADSTS65001: The user or administrator has not consented")
    credential, _ = interactive(lambda request: token_reply("x"), browser)
    with pytest.raises(AuthError, match="AADSTS65001") as caught:
        credential.get_token(GRAPH, TENANT)
    assert "consent" in (caught.value.hint or "")


def test_the_loopback_receiver_takes_one_redirect_and_ignores_other_requests():
    receiver = LoopbackReceiver()
    try:
        port = urlsplit(receiver.redirect_uri).port

        statuses: list[int] = []

        def browser() -> None:
            for path in ("/favicon.ico", "/?code=abc&state=xyz"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
                        statuses.append(r.status)
                except urllib.error.HTTPError as exc:
                    statuses.append(exc.code)

        thread = threading.Thread(target=browser)
        thread.start()
        assert receiver.wait(5) == {"code": "abc", "state": "xyz"}
        thread.join()
        assert statuses == [404, 200]
    finally:
        receiver.close()


def test_the_loopback_receiver_times_out():
    receiver = LoopbackReceiver()
    try:
        with pytest.raises(AuthError, match="no sign-in completed"):
            receiver.wait(0.6)
    finally:
        receiver.close()


# Device code ---------------------------------------------------------------------


def device(replies, clock: FakeClock, notices: list[str]):
    session, adapter = fake_session(lambda request: next(replies))
    credential = DeviceCodeCredential(
        CLIENT_ID,
        session=session,
        clock=lambda: NOW,
        sleep=clock.sleep,
        monotonic=clock,
        notify=notices.append,
    )
    return credential, adapter


DEVICE_FLOW = (
    200,
    {
        "device_code": "dc",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/devicelogin",
        "interval": 5,
        "expires_in": 900,
        "message": "To sign in, open https://microsoft.com/devicelogin and enter ABCD-EFGH",
    },
)


def test_the_device_code_flow_polls_at_the_interval_and_backs_off_when_asked():
    replies = iter(
        [
            DEVICE_FLOW,
            (400, {"error": "authorization_pending", "error_description": "AADSTS70016: pending"}),
            (400, {"error": "slow_down", "error_description": "slow down"}),
            token_reply("device-token"),
        ]
    )
    clock, notices = FakeClock(), []
    credential, adapter = device(replies, clock, notices)
    assert credential.get_token(GRAPH, TENANT).token == "device-token"
    assert clock.sleeps == [5, 5, 10]
    assert "ABCD-EFGH" in notices[0]
    assert form_body(adapter.requests[-1])["grant_type"].endswith("device_code")


def test_a_declined_or_expired_device_code_fails():
    declined = iter(
        [DEVICE_FLOW, (400, {"error": "authorization_declined", "error_description": "no"})]
    )
    credential, _ = device(declined, FakeClock(), [])
    with pytest.raises(AuthError, match="authorization_declined"):
        credential.get_token(GRAPH, TENANT)

    pending = (400, {"error": "authorization_pending", "error_description": "pending"})
    forever = iter([DEVICE_FLOW, *[pending] * 500])
    credential, _ = device(forever, FakeClock(), [])
    with pytest.raises(AuthError, match="expired"):
        credential.get_token(GRAPH, TENANT)


def test_the_factory_builds_both_delegated_flows():
    interactive_profile = Profile("me", TENANT, auth="interactive", client_id=CLIENT_ID)
    device_profile = Profile("me", TENANT, auth="device-code", client_id=CLIENT_ID)
    assert isinstance(credential_for(interactive_profile), InteractiveCredential)
    assert isinstance(credential_for(device_profile), DeviceCodeCredential)
    assert CLIENT_ID in repr(credential_for(device_profile))
