import json
import logging
import os
import stat
import sys
import types

import pytest

from libre_devops_helpers.core import brand, token_store
from libre_devops_helpers.core.errors import AuthError, ConfigError
from libre_devops_helpers.core.token_store import (
    FileStore,
    KeyringStore,
    MemoryStore,
    default_path,
    open_store,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_memory_store_keeps_values_for_this_process_only():
    store = MemoryStore()
    assert store.load("k") is None
    store.save("k", "v")
    assert store.load("k") == "v"
    first, second = store.delete("k"), store.delete("k")
    assert (first, second) == (True, False)


def test_the_file_store_round_trips_and_records_when_it_saved(tmp_path):
    path = tmp_path / "state" / "refresh-tokens.json"
    store = FileStore(path)
    assert store.load("k") is None
    store.save("k", "refresh-1")
    store.save("other", "refresh-2")
    assert FileStore(path).load("k") == "refresh-1"  # a new process sees it
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["k"]["value"] == "refresh-1"
    assert "saved" in saved["k"]
    deleted = [store.delete("k"), store.delete("k"), store.delete("other")]
    assert deleted == [True, False, True]
    assert not path.exists()  # the last one out removes the file
    assert list(path.parent.iterdir()) == []  # and no temporary file is left


@posix_only
def test_the_file_and_its_folder_are_private(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "umask", os.umask)  # restored whatever happens
    os.umask(0o022)
    path = tmp_path / "state" / "refresh-tokens.json"
    FileStore(path).save("k", "v")
    assert mode(path) == 0o600
    assert mode(path.parent) == 0o700


@posix_only
def test_a_file_other_accounts_can_read_is_refused_then_replaced_by_a_private_one(tmp_path):
    path = tmp_path / "refresh-tokens.json"
    FileStore(path).save("k", "v")
    path.chmod(0o644)
    store = FileStore(path)
    with pytest.raises(AuthError, match="can be read by other accounts") as caught:
        store.load("k")
    assert "sign-out" in (caught.value.hint or "")
    store.save("k", "fresh")
    assert mode(path) == 0o600
    assert store.load("k") == "fresh"


def test_a_damaged_file_is_ignored_with_a_warning(tmp_path, caplog):
    path = tmp_path / "refresh-tokens.json"
    FileStore(path).save("k", "v")
    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert FileStore(path).load("k") is None
    assert "cannot be read" in caplog.text


def test_an_unwritable_location_is_an_auth_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(AuthError, match="the token cache"):
        FileStore(blocker / "refresh-tokens.json").save("k", "v")


def reverse(data: bytes) -> bytes:
    return data[::-1]


def test_an_encrypted_file_store_holds_only_the_protected_bytes(tmp_path):
    path = tmp_path / "refresh-tokens.dpapi"
    store = FileStore(path, protect=reverse, unprotect=reverse)
    store.save("k", "secret-refresh")
    assert b"secret-refresh" not in path.read_bytes()
    assert FileStore(path, protect=reverse, unprotect=reverse).load("k") == "secret-refresh"


def test_an_encrypted_file_for_another_account_is_ignored(tmp_path):
    path = tmp_path / "refresh-tokens.dpapi"
    FileStore(path, protect=reverse, unprotect=reverse).save("k", "v")

    def refuse(data: bytes) -> bytes:
        raise OSError("the data is invalid")

    assert FileStore(path, protect=reverse, unprotect=refuse).load("k") is None


class FakeKeyring:
    """Enough of the keyring package: three functions and its error class."""

    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.broken = broken
        self.errors = types.SimpleNamespace(KeyringError=RuntimeError)

    def _check(self) -> None:
        if self.broken:
            raise RuntimeError("No recommended backend was available")

    def get_password(self, service: str, key: str) -> str | None:
        self._check()
        return self.values.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self._check()
        self.values[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self._check()
        del self.values[(service, key)]


def test_the_keychain_store_uses_the_tools_service_name():
    backend = FakeKeyring()
    store = KeyringStore(backend=backend)
    store.save("k", "v")
    assert backend.values == {(f"{brand.COMMAND} sign-in", "k"): "v"}
    assert store.load("k") == "v"
    first, second = store.delete("k"), store.delete("k")
    assert (first, second) == (True, False)
    assert store.load("k") is None


def test_a_keychain_that_cannot_be_reached_says_what_to_do_instead():
    store = KeyringStore(backend=FakeKeyring(broken=True))
    with pytest.raises(AuthError, match="cannot read the keychain") as caught:
        store.load("k")
    assert 'token_cache = "file"' in (caught.value.hint or "")
    with pytest.raises(AuthError, match="cannot write to the keychain"):
        store.save("k", "v")


def test_the_keychain_without_the_keyring_package_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # makes the import fail
    with pytest.raises(ConfigError, match="needs the keyring package") as caught:
        KeyringStore()
    assert f"{brand.DISTRIBUTION}[keychain]" in (caught.value.hint or "")


def test_the_default_file_is_per_user_and_can_be_moved():
    environ = {"XDG_STATE_HOME": "/state"}
    assert str(default_path(environ=environ, platform="linux")).replace("\\", "/") == (
        f"/state/{brand.CONFIG_DIR}/refresh-tokens.json"
    )
    windows = default_path(
        encrypted=True, environ={"LOCALAPPDATA": "C:/Users/a/AppData/Local"}, platform="win32"
    )
    assert windows.name == "refresh-tokens.dpapi"
    assert windows.parent.name == brand.CONFIG_DIR
    moved = {token_store.FILE_ENV: "/tmp/cache/tokens.json"}
    assert default_path(environ=moved).name == "tokens.json"
    assert default_path(encrypted=True, environ=moved).name == "tokens.dpapi"


def test_open_store_builds_what_token_cache_names(tmp_path, monkeypatch):
    environ = {token_store.FILE_ENV: str(tmp_path / "tokens.json")}
    assert isinstance(open_store("memory"), MemoryStore)
    file_store = open_store("file", environ=environ)
    assert isinstance(file_store, FileStore)
    assert file_store.path == tmp_path / "tokens.json"
    windows = open_store("keychain", environ=environ, platform="win32")
    assert isinstance(windows, FileStore)
    assert windows.path.suffix == ".dpapi"
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    assert isinstance(open_store("keychain", platform="linux"), KeyringStore)
    with pytest.raises(ConfigError, match="token_cache must be one of"):
        open_store("cloud")


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anywhere")
def test_a_folder_it_cannot_write_to_is_an_auth_error(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        with pytest.raises(AuthError, match="cannot write the token cache"):
            FileStore(folder / "refresh-tokens.json").save("k", "v")
    finally:
        folder.chmod(0o700)
