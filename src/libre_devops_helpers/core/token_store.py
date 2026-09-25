"""Where a sign-in's refresh token is kept between commands: a profile's token_cache.

Three choices, from safest to least guarded (profiles use ``file`` unless they say
otherwise, since it works on a headless machine):

- ``memory``: nowhere. The sign-in lasts one command and is gone after.
- ``keychain``: the operating system's own store, locked to your account. Keychain on
  macOS and the Secret Service (GNOME Keyring, KWallet) on Linux, through the optional
  ``keyring`` package; on Windows, a file encrypted with DPAPI for your Windows account,
  since Credential Manager's size limit is too small for a refresh token.
- ``file`` (the default for profiles): a plaintext JSON file that only your account may
  read (mode 0600), as the Azure CLI keeps its own tokens on Linux. Anyone who can act as
  you, or as root, or who gets a copy of the file (a backup, say), can use what is in it.

A refresh token is as good as a sign-in until it expires or is revoked, so a file that
other accounts can read is refused rather than used, as ssh refuses a readable key.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import AuthError, ConfigError

log = logging.getLogger(__name__)

TOKEN_CACHES = ("memory", "keychain", "file")
# Where a profile keeps its sign-in unless it says otherwise: a private file, which works
# on a headless machine as well as a desktop.
DEFAULT_TOKEN_CACHE = "file"
FILE_ENV = brand.env_var("TOKEN_CACHE")
KEYCHAIN_SERVICE = f"{brand.COMMAND} sign-in"
_KEYCHAIN_HINT = f"install the keychain extra: uv tool install '{brand.DISTRIBUTION}[keychain]'"


class TokenStore(Protocol):
    """Named secrets that outlast one command (or, for MemoryStore, do not)."""

    def load(self, key: str) -> str | None:
        """The value kept under ``key``, or None when there is none."""

    def save(self, key: str, value: str) -> None:
        """Keep ``value`` under ``key``, replacing what was there."""

    def delete(self, key: str) -> bool:
        """Forget ``key``. True when there was something to forget."""


class MemoryStore:
    """Kept in this process only, so a sign-in lasts one command: ``token_cache = "memory"``,
    and what a credential keeps its sign-in in when it is given no store."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def load(self, key: str) -> str | None:
        """The value kept under ``key`` in this process, or None."""
        with self._lock:
            return self._values.get(key)

    def save(self, key: str, value: str) -> None:
        """Keep ``value`` under ``key`` until this process ends."""
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> bool:
        """Forget ``key``. True when there was something to forget."""
        with self._lock:
            return self._values.pop(key, None) is not None


class FileStore:
    """Values in one JSON file, private to your account, replaced whole on every write.

    The directory is created 0700 and the file 0600, through a temporary file renamed
    into place, so a crash never leaves half a file and a reader never sees one. A change
    (read, change, write) holds a lock file beside it, so two commands at once, in two
    terminals, say, never lose each other's sign-ins. With ``protect`` and ``unprotect``
    (DPAPI on Windows) the file holds their encrypted bytes rather than plain JSON.
    """

    def __init__(
        self,
        path: Path,
        *,
        protect: Callable[[bytes], bytes] | None = None,
        unprotect: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self.path = path
        self._protect = protect
        self._unprotect = unprotect
        self._lock = threading.Lock()

    def load(self, key: str) -> str | None:
        """The value kept under ``key``, or None. Refuses a file other accounts can read."""
        with self._lock:
            entry = self._read().get(key)
        value = entry.get("value") if isinstance(entry, dict) else None
        return value if isinstance(value, str) and value else None

    def save(self, key: str, value: str) -> None:
        """Keep ``value`` under ``key``, holding the lock while the file is rewritten."""
        with self._changing():
            data = self._read(refuse_exposed=False)
            data[key] = {"value": value, "saved": datetime.now(UTC).isoformat(timespec="seconds")}
            self._write(data)

    def delete(self, key: str) -> bool:
        """Forget ``key``, removing the file with the last value. True when there was one."""
        if not self.path.exists():
            return False
        with self._changing():
            data = self._read(refuse_exposed=False)
            if key not in data:
                return False
            del data[key]
            if data:
                self._write(data)
            else:
                self.path.unlink(missing_ok=True)
            return True

    @contextmanager
    def _changing(self) -> Iterator[None]:
        """Hold the file for a read, change and write: against this process's other threads
        (a lock) and against other processes (a lock file, which the system lets go of if
        the process holding it dies, so a crash never leaves the cache locked).

        The lock file is never removed: removing it while another command waits on it
        would let a third lock a new one, and both change the cache at once.
        """
        with self._lock:
            self._make_folder()
            lock_path = self.path.with_name(f".{self.path.name}.lock")
            try:
                descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as exc:
                raise AuthError(f"cannot write the token cache {self.path}: {exc}") from None
            try:
                try:
                    _lock_file(descriptor)
                except OSError as exc:
                    raise AuthError(
                        f"cannot lock the token cache {self.path}: {exc}",
                        hint="another command may be signing in: try again when it has finished",
                    ) from None
                try:
                    yield
                finally:
                    _unlock_file(descriptor)
            finally:
                os.close(descriptor)

    def _read(self, *, refuse_exposed: bool = True) -> dict[str, Any]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise AuthError(f"cannot read the token cache {self.path}: {exc}") from None
        if refuse_exposed and _exposed(self.path):
            raise AuthError(
                f"the token cache {self.path} can be read by other accounts, so it is not used",
                hint=(
                    f"delete it (a new one is private): what it held may have been seen, so "
                    f"also run {brand.command('entra sign-out')} and sign out everywhere if "
                    "that matters"
                ),
            )
        try:
            if self._unprotect is not None:
                raw = self._unprotect(raw)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as exc:
            # A damaged cache, or one encrypted for another account: start again.
            log.warning("ignoring the token cache %s, which cannot be read: %s", self.path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: Mapping[str, Any]) -> None:
        payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        if self._protect is not None:
            payload = self._protect(payload)
        try:
            # A name of its own (mkstemp), created 0600, so no other writer shares it.
            descriptor, name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise AuthError(f"cannot write the token cache {self.path}: {exc}") from None

    def _make_folder(self) -> None:
        """The file's folder, private (0700) when this creates it."""
        folder = self.path.parent
        try:
            folder.mkdir(parents=True, mode=0o700)
        except FileExistsError:
            return
        except OSError as exc:
            raise AuthError(f"cannot create the token cache folder {folder}: {exc}") from None
        os.chmod(folder, 0o700)  # mkdir's mode is narrowed by the umask, not widened


def _lock_file(descriptor: int) -> None:
    """Wait for, then take, an exclusive lock on an open file."""
    if sys.platform == "win32":
        import msvcrt

        # Locks the first byte; tries once a second for 10 seconds, then fails.
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_file(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


class KeyringStore:
    """Values in the operating system's keychain, through the ``keyring`` package."""

    def __init__(
        self, service: str = KEYCHAIN_SERVICE, *, backend: ModuleType | None = None
    ) -> None:
        self.service = service
        self._backend = backend if backend is not None else _keyring()
        errors = getattr(backend, "errors", None)
        self._error: type[Exception] = getattr(errors, "KeyringError", Exception)

    def load(self, key: str) -> str | None:
        """The value the keychain keeps under ``key``, or None."""
        try:
            return self._backend.get_password(self.service, key) or None
        except self._error as exc:
            raise self._failure("read", exc) from None

    def save(self, key: str, value: str) -> None:
        """Keep ``value`` in the keychain under ``key``."""
        try:
            self._backend.set_password(self.service, key, value)
        except self._error as exc:
            raise self._failure("write to", exc) from None

    def delete(self, key: str) -> bool:
        """Remove ``key`` from the keychain. True when there was something to remove."""
        try:
            if self._backend.get_password(self.service, key) is None:
                return False
            self._backend.delete_password(self.service, key)
        except self._error as exc:
            raise self._failure("write to", exc) from None
        return True

    def _failure(self, action: str, exc: Exception) -> AuthError:
        return AuthError(
            f"cannot {action} the keychain: {exc}",
            hint=(
                "on Linux this needs a Secret Service (GNOME Keyring or KWallet) running; "
                'without one, use token_cache = "file" or "memory"'
            ),
        )


def _keyring() -> ModuleType:
    """The ``keyring`` package: optional (the keychain extra), so imported only when asked for."""
    try:
        return importlib.import_module("keyring")
    except ImportError:
        raise ConfigError(
            'token_cache = "keychain" needs the keyring package', hint=_KEYCHAIN_HINT
        ) from None


def default_path(
    *, encrypted: bool = False, environ: Mapping[str, str] = os.environ, platform: str = ""
) -> Path:
    """Where the file stores live: per user, never beside a config file in a repository.

    The brand's ``TOKEN_CACHE`` variable names a file instead. Otherwise it is
    ``%LOCALAPPDATA%\\<tool>`` on Windows and ``$XDG_STATE_HOME/<tool>`` (by default
    ``~/.local/state/<tool>``) elsewhere.
    """
    name = "refresh-tokens.dpapi" if encrypted else "refresh-tokens.json"
    override = environ.get(FILE_ENV)
    if override:
        path = Path(override).expanduser()
        return path.with_suffix(".dpapi") if encrypted else path
    if (platform or sys.platform) == "win32":
        base = Path(environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / brand.CONFIG_DIR / name


def open_store(
    kind: str, *, environ: Mapping[str, str] = os.environ, platform: str = ""
) -> TokenStore:
    """The store a profile's ``token_cache`` names."""
    if kind == "memory":
        return MemoryStore()
    if kind == "file":
        return FileStore(default_path(environ=environ, platform=platform))
    if kind == "keychain":
        if (platform or sys.platform) == "win32":
            from libre_devops_helpers.core import dpapi  # Windows only

            return FileStore(
                default_path(encrypted=True, environ=environ, platform=platform),
                protect=dpapi.protect,
                unprotect=dpapi.unprotect,
            )
        return KeyringStore()
    raise ConfigError(f"token_cache must be one of {', '.join(TOKEN_CACHES)}, not {kind!r}")


def _exposed(path: Path) -> bool:
    """True when accounts other than the owner may read ``path`` (POSIX permissions)."""
    if os.name != "posix":
        return False  # Windows: the per-user profile folder's ACL keeps others out
    return bool(path.stat().st_mode & 0o077)
