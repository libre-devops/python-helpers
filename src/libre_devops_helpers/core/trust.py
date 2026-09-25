"""Which certificates HTTPS calls trust: the public roots, the operating system's, and yours.

By default every call trusts three sets together:

- the public roots ``requests`` ships (certifi);
- the operating system's certificate store, where IT installs a TLS-inspecting proxy's
  root: the Windows store, the macOS system keychains, or the Linux system bundle;
- the extra certificates the config file's ``ca_bundle`` names.

They go into one PEM file, which every call verifies against and which the Azure CLI is
handed as ``REQUESTS_CA_BUNDLE``, so both trust the same things. Adding the OS store only
ever adds trust: a site with a public certificate still verifies.

``LDO_CA_BUNDLE``, ``REQUESTS_CA_BUNDLE`` or ``CURL_CA_BUNDLE`` (the first one set) names a
bundle to use exactly as it is instead, nothing added: the way to opt out.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import requests.certs

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import ConfigError

log = logging.getLogger(__name__)

EXPLICIT_ENV = (brand.env_var("CA_BUNDLE"), "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_PEM = re.compile(r"-----BEGIN CERTIFICATE-----\s.+?\s-----END CERTIFICATE-----", re.S)
# Server authentication, the purpose a Windows store entry must allow to count here.
_SERVER_AUTH = "1.3.6.1.5.5.7.3.1"
_MACOS_KEYCHAINS = (
    "/System/Library/Keychains/SystemRootCertificates.keychain",
    "/Library/Keychains/System.keychain",
)
# Where Linux distributions keep the system bundle, when OpenSSL's defaults point nowhere.
_LINUX_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Alpine
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL, Fedora
    "/etc/ssl/ca-bundle.pem",  # SUSE
    "/etc/ssl/cert.pem",
)
_KEEP_OLD_BUNDLES = 7 * 24 * 3600


@dataclass(frozen=True)
class Bundle:
    """The bundle calls verify against, and where its certificates came from."""

    path: str
    explicit: str | None  # the variable that named it, when one did
    public: int = 0
    system: int = 0
    extra: int = 0


def explicit_bundle(environ: Mapping[str, str] = os.environ) -> tuple[str, Path] | None:
    """The bundle a variable names, as (variable, path), or None. It must exist."""
    for name in EXPLICIT_ENV:
        value = (environ.get(name) or "").strip()
        if value:
            path = Path(value).expanduser()
            if not path.is_file():
                raise ConfigError(
                    f"{name} names {path}, which is not a file",
                    hint=f"point it at a PEM bundle, or unset it to trust the OS store ({name})",
                )
            return name, path
    return None


def split_pem(text: str) -> list[str]:
    """Each certificate in PEM ``text``, normalised so duplicates compare equal."""
    return ["\n".join(line.strip() for line in block.splitlines()) for block in _PEM.findall(text)]


def system_certificates(
    platform: str = "",
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    enum_certificates: Callable[[str], list[tuple[bytes, str, object]]] | None = None,
) -> list[str]:
    """The operating system's trusted certificates as PEM, or [] when they cannot be read.

    Never raises: a machine whose store cannot be read still has the public roots.
    """
    platform = platform or sys.platform
    try:
        if platform == "win32":
            return _windows(enum_certificates or getattr(ssl, "enum_certificates", None))
        if platform == "darwin":
            return _macos(run)
        return _linux()
    except Exception as exc:  # the store is a bonus; its failure must not stop a call
        log.warning("cannot read the system certificate store: %s", exc)
        return []


def _windows(enum: Callable[[str], list[tuple[bytes, str, object]]] | None) -> list[str]:
    if enum is None:
        return []
    found: list[str] = []
    for store in ("ROOT", "CA"):
        for der, encoding, trust in enum(store):
            usable = trust is True or (isinstance(trust, set | frozenset) and _SERVER_AUTH in trust)
            if encoding == "x509_asn" and usable:
                found.append(ssl.DER_cert_to_PEM_cert(der))
    return found


def _macos(run: Callable[..., subprocess.CompletedProcess[str]]) -> list[str]:
    keychains = [path for path in _MACOS_KEYCHAINS if Path(path).exists()]
    if not keychains:
        return []
    result = run(
        ["/usr/bin/security", "find-certificate", "-a", "-p", *keychains],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(f"security exited {result.returncode}")
    return split_pem(result.stdout)


def _linux() -> list[str]:
    paths = ssl.get_default_verify_paths()
    candidates = [paths.cafile, paths.openssl_cafile, *_LINUX_BUNDLES]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return split_pem(Path(candidate).read_text(encoding="utf-8", errors="replace"))
    return []


def _loadable(certificates: list[str]) -> list[str]:
    """The certificates OpenSSL can load: one bad entry would fail the whole bundle."""
    if not certificates:
        return []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_verify_locations(cadata="\n".join(certificates))
        return certificates
    except ssl.SSLError:
        pass
    kept = []
    for certificate in certificates:
        try:
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=certificate)
            kept.append(certificate)
        except ssl.SSLError:
            log.debug("skipping a certificate OpenSSL cannot load")
    return kept


def build(extra: Path | None = None, *, system: list[str] | None = None) -> tuple[str, Bundle]:
    """The combined bundle's text, and its counts (its path is filled in by ``resolve``)."""
    public = split_pem(Path(requests.certs.where()).read_text(encoding="utf-8"))
    seen = dict.fromkeys(public)
    from_system = [
        cert for cert in _loadable(split_pem("\n".join(system or []))) if cert not in seen
    ]
    seen.update(dict.fromkeys(from_system))
    from_extra: list[str] = []
    if extra is not None:
        if not extra.is_file():
            raise ConfigError(f"ca_bundle not found: {extra}")
        text = extra.read_text(encoding="utf-8", errors="replace")
        loaded = _loadable(split_pem(text))
        if not loaded:
            raise ConfigError(f"ca_bundle {extra} holds no certificate OpenSSL can load")
        from_extra = [cert for cert in loaded if cert not in seen]
    body = "\n".join([*seen, *from_extra]) + "\n"
    return body, Bundle("", None, len(public), len(from_system), len(from_extra))


def cache_dir(environ: Mapping[str, str] = os.environ, platform: str = "") -> Path:
    """Per user: ``%LOCALAPPDATA%\\<tool>\\cache`` on Windows, ``$XDG_CACHE_HOME/<tool>``
    (``~/.cache/<tool>``) elsewhere."""
    if (platform or sys.platform) == "win32":
        base = Path(environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / brand.CONFIG_DIR / "cache"
    return Path(environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / brand.CONFIG_DIR


def write(body: str, folder: Path) -> Path:
    """``body`` in ``folder``, named by its hash so it is reused until the trust changes."""
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    target = folder / f"ca-bundle-{digest}.pem"
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_file() and target.read_text(encoding="utf-8") == body:
            return target
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=".ca-bundle-", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
        os.replace(temporary, target)
        _prune(folder, keep=target)
        return target
    except OSError as exc:
        # A read-only home (some containers): a private file of its own, gone at exit.
        log.info("cannot write the CA bundle in %s (%s); using a temporary file", folder, exc)
        handle, temporary = tempfile.mkstemp(prefix=f"{brand.COMMAND}-ca-bundle-", suffix=".pem")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
        import atexit

        atexit.register(lambda: Path(temporary).unlink(missing_ok=True))
        return Path(temporary)


def _prune(folder: Path, *, keep: Path) -> None:
    cutoff = time.time() - _KEEP_OLD_BUNDLES
    for old in folder.glob("ca-bundle-*.pem"):
        try:
            if old != keep and old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass


class _Resolved:
    lock = threading.Lock()
    bundles: dict[tuple[str, str], Bundle] = {}  # noqa: RUF012 - one process-wide cache


def resolve(
    extra: Path | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    system: Callable[[], list[str]] = system_certificates,
) -> Bundle:
    """The bundle to verify against: an explicit one as it is, else the combined one.

    Built once per process for each ``extra``; the file is reused across runs.
    """
    named = explicit_bundle(environ)
    if named is not None:
        variable, path = named
        return Bundle(str(path), variable)
    key = (str(extra or ""), str(cache_dir(environ)))
    with _Resolved.lock:
        found = _Resolved.bundles.get(key)
        if found is None:
            body, counts = build(extra, system=system())
            path = write(body, cache_dir(environ))
            found = Bundle(str(path), None, counts.public, counts.system, counts.extra)
            _Resolved.bundles[key] = found
            log.debug(
                "CA bundle %s: %d public, %d from the OS store, %d from ca_bundle",
                path,
                found.public,
                found.system,
                found.extra,
            )
        return found


def forget() -> None:
    """Drop the process's cached bundles (for tests, and after the trust changes)."""
    with _Resolved.lock:
        _Resolved.bundles.clear()
