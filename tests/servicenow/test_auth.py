import json
import re

import pytest

from fakes.http import fake_session, form_body
from fakes.servicenow import (
    CLIENT_ID,
    CLIENT_SECRET,
    INSTANCE,
    PASSWORD,
    REDIRECT,
    USERNAME,
    FakeInstance,
)
from libre_devops_helpers.core.errors import AuthError, ReauthRequired
from libre_devops_helpers.core.token_store import FileStore, MemoryStore
from libre_devops_helpers.servicenow.auth import (
    BasicCredential,
    OAuthApp,
    OAuthCredential,
    credential_for,
)
from libre_devops_helpers.servicenow.config import Profile

KEY = "servicenow|dev12345.service-now.com|client|dev"


def oauth(instance, *, sign_in="password", secret=CLIENT_SECRET, store=None, ask=None, **options):
    session, _ = fake_session(instance)
    notices: list[str] = []
    credential = OAuthCredential(
        OAuthApp(INSTANCE, CLIENT_ID, secret, REDIRECT),
        key=KEY,
        sign_in=sign_in,
        username=USERNAME,
        store=store or MemoryStore(),
        ask=ask,
        session=session,
        notify=notices.append,
        has_browser=lambda: False,
        **options,
    )
    return credential, notices


def test_basic_encodes_the_username_and_password_and_hides_them():
    credential = BasicCredential("ana", "p4ss")
    assert credential.authorization() == "YW5hOnA0c3M="
    assert "p4ss" not in repr(credential)
    with pytest.raises(AuthError, match="needs a password"):
        BasicCredential("ana", "")


def test_the_password_grant_signs_in_once_then_the_kept_refresh_token_serves():
    instance = FakeInstance()
    store = MemoryStore()
    first, _ = oauth(instance, store=store, password=lambda: PASSWORD)
    token = first.get_token()
    assert token.token in instance.access
    assert token.resource == INSTANCE
    # A new credential, as the next command makes: no password needed now.
    later, _ = oauth(instance, store=store)
    assert later.get_token().token in instance.access
    assert instance.grants == ["password", "refresh_token"]
    kept = json.loads(store.load(KEY))
    assert set(kept) == {"refresh_token"}  # the secret came from the environment


def test_without_a_kept_sign_in_or_a_password_it_says_how_to_sign_in():
    credential, _ = oauth(FakeInstance(), sign_in_hint="run ldo snow sign-in")
    with pytest.raises(ReauthRequired, match="no password") as caught:
        credential.get_token()
    assert caught.value.hint == "run ldo snow sign-in"


def test_a_password_can_be_asked_for_hidden():
    instance = FakeInstance()
    asked: list[tuple[str, bool]] = []

    def ask(question, secret):
        asked.append((question, secret))
        return PASSWORD

    credential, _ = oauth(instance, ask=ask)
    credential.get_token()
    assert asked == [(f"ServiceNow password for {USERNAME}", True)]


def test_a_client_secret_typed_in_is_kept_with_the_sign_in(tmp_path):
    instance = FakeInstance()
    store = FileStore(tmp_path / "refresh-tokens.json")

    def answer(question, secret):
        return CLIENT_SECRET if "Client secret" in question else PASSWORD

    credential, _ = oauth(instance, secret=None, store=store, ask=answer)
    credential.get_token()
    assert json.loads(store.load(KEY))["client_secret"] == CLIENT_SECRET
    # The next command needs neither the secret nor the password.
    later, _ = oauth(instance, secret=None, store=store)
    assert later.get_token().token in instance.access


def test_a_refused_refresh_token_is_forgotten_and_it_signs_in_again():
    instance = FakeInstance()
    store = MemoryStore()
    store.save(KEY, json.dumps({"refresh_token": "revoked"}))
    credential, notices = oauth(instance, store=store, password=lambda: PASSWORD)
    assert credential.get_token().token in instance.access
    assert instance.grants == ["refresh_token", "password"]
    assert any("refused" in notice for notice in notices)


def test_the_browser_sign_in_uses_pkce_and_the_pasted_address():
    instance = FakeInstance()
    notices: list[str] = []

    def paste(question, secret):
        url = re.search(r"https://\S+/oauth_auth\.do\?\S+", notices[-1]).group(0)
        return instance.approve(url)

    session, adapter = fake_session(instance)
    credential = OAuthCredential(
        OAuthApp(INSTANCE, CLIENT_ID, CLIENT_SECRET, REDIRECT),
        key=KEY,
        sign_in="browser",
        ask=paste,
        session=session,
        notify=notices.append,
        has_browser=lambda: False,
    )
    assert credential.get_token().token in instance.access
    exchange = form_body(adapter.requests[-1])
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["redirect_uri"] == REDIRECT
    assert "code_verifier" in exchange
    assert "paste it here" in notices[-1]


def test_a_browser_sign_in_with_the_wrong_address_or_a_refusal_fails():
    instance = FakeInstance()
    replies = iter([f"{REDIRECT}?code=abc&state=forged"])
    credential, _ = oauth(instance, sign_in="browser", ask=lambda q, s: next(replies))
    with pytest.raises(AuthError, match="state does not match"):
        credential.get_token()
    notices: list[str] = []

    def deny(question, secret):
        url = re.search(r"https://\S+/oauth_auth\.do\?\S+", notices[-1]).group(0)
        return instance.approve(url, deny=True)

    session, _ = fake_session(instance)
    refused = OAuthCredential(
        OAuthApp(INSTANCE, CLIENT_ID, CLIENT_SECRET, REDIRECT),
        key=KEY,
        ask=deny,
        session=session,
        notify=notices.append,
        has_browser=lambda: False,
    )
    with pytest.raises(AuthError, match="access_denied"):
        refused.get_token()


def test_a_browser_sign_in_with_nobody_to_paste_says_how_to_sign_in():
    credential, _ = oauth(FakeInstance(), sign_in="browser")
    with pytest.raises(ReauthRequired, match="needs a browser"):
        credential.get_token()


def test_a_wrong_client_secret_or_password_is_explained():
    credential, _ = oauth(FakeInstance(), secret="wrong", password=lambda: PASSWORD)
    with pytest.raises(AuthError) as caught:
        credential.get_token()
    assert "client id and secret" in (caught.value.hint or "")
    credential, _ = oauth(FakeInstance(), password=lambda: "wrong")
    with pytest.raises(AuthError) as caught:
        credential.get_token()
    assert "username and password" in (caught.value.hint or "")


def test_sign_in_ignores_the_kept_one_and_sign_out_forgets_it():
    instance = FakeInstance()
    store = MemoryStore()
    credential, _ = oauth(instance, store=store, password=lambda: PASSWORD)
    credential.get_token()
    credential.sign_in()
    assert instance.grants == ["password", "password"]
    assert credential.has_kept_sign_in()
    assert credential.sign_out() is True
    assert not credential.has_kept_sign_in()
    assert "p4ss" not in repr(credential)


def profile(**overrides) -> Profile:
    return Profile("dev", INSTANCE, **overrides)


def test_the_factory_reads_secrets_from_the_environment(tmp_path):
    environ = {"SNOW_INSTANCE_PASSWORD": PASSWORD, "SNOW_CLIENT_SECRET": CLIENT_SECRET}
    basic = credential_for(profile(auth="basic", username="ana"), environ=environ)
    assert isinstance(basic, BasicCredential)
    oauth_credential = credential_for(
        profile(client_id=CLIENT_ID), environ=environ, store=MemoryStore()
    )
    assert isinstance(oauth_credential, OAuthCredential)
    assert oauth_credential.app.client_secret == CLIENT_SECRET
    assert oauth_credential.key == f"servicenow|dev12345.service-now.com|{CLIENT_ID}|dev"
    from_env = credential_for(
        profile(), environ={"SNOW_CLIENT_ID": "env-client"}, store=MemoryStore()
    )
    assert from_env.app.client_id == "env-client"


@pytest.mark.parametrize(
    ("overrides", "environ", "message"),
    [
        ({"auth": "basic"}, {"SNOW_INSTANCE_PASSWORD": "x"}, "has no username"),
        ({"auth": "basic", "username": "ana"}, {}, "needs a password"),
        ({}, {}, "has no OAuth client id"),
        ({"client_id": "c", "sign_in": "password"}, {}, "has no username"),
    ],
)
def test_the_factory_says_what_is_missing(overrides, environ, message):
    with pytest.raises(AuthError, match=message):
        credential_for(profile(**overrides), environ=environ, store=MemoryStore())


class BrokenStore:
    def load(self, key):
        raise AuthError("the keychain is locked")

    def save(self, key, value):
        raise AuthError("the keychain is locked")

    def delete(self, key):
        raise AuthError("the keychain is locked")


def test_a_store_that_fails_is_reported_and_the_sign_in_still_works():
    credential, notices = oauth(FakeInstance(), store=BrokenStore(), password=lambda: PASSWORD)
    assert credential.get_token().token
    assert any("cannot be used" in notice for notice in notices)
    assert any("could not be kept" in notice for notice in notices)
    assert not credential.has_kept_sign_in()


@pytest.mark.parametrize(
    "kept", ["not json", json.dumps(["a list"]), json.dumps({"refresh_token": 5})]
)
def test_a_damaged_kept_sign_in_is_treated_as_none(kept):
    store = MemoryStore()
    store.save(KEY, kept)
    credential, _ = oauth(FakeInstance(), store=store, password=lambda: PASSWORD)
    assert not credential.has_kept_sign_in()
    assert credential.get_token().token


def test_a_token_response_without_a_token_is_an_error():
    instance = FakeInstance()
    original = instance._token

    def no_token(form):
        status, body = original(form)
        body.pop("access_token", None)
        return status, body

    instance._token = no_token
    credential, _ = oauth(instance, password=lambda: PASSWORD)
    with pytest.raises(AuthError, match="no access_token"):
        credential.get_token()


def test_the_credential_needs_a_client_id_and_a_username_for_the_password_grant():
    with pytest.raises(AuthError, match="client id"):
        OAuthCredential(OAuthApp(INSTANCE, "", CLIENT_SECRET, REDIRECT), key=KEY)
    with pytest.raises(AuthError, match="needs a username"):
        OAuthCredential(
            OAuthApp(INSTANCE, CLIENT_ID, CLIENT_SECRET, REDIRECT), key=KEY, sign_in="password"
        )
