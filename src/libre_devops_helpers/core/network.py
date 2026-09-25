"""Corporate networks: which proxy each call goes through, and what it trusts.

Every HTTPS call this package makes, and every ``az`` the CLI runs, follows one set of
rules, set once with ``configure``:

1. Loopback and link-local addresses never use a proxy: a sign-in's redirect to
   localhost, and the managed identity endpoint (169.254.169.254).
2. A host that ``no_proxy`` (the config file's) or ``NO_PROXY`` lists goes direct.
3. Otherwise the proxy is ``LDO_PROXY_ADDRESS``, else the config file's ``proxy``, else
   ``HTTPS_PROXY`` / ``HTTP_PROXY`` / ``ALL_PROXY``, else the operating system's setting
   (Windows and macOS), else none.

A proxy that wants a sign-in of its own (NTLM or Kerberos, as corporate ones often do) is
reached through a local one that handles it, such as cntlm or Px: point the proxy at it,
e.g. ``LDO_PROXY_ADDRESS=127.0.0.1:3128``. An address without a scheme is taken as
``http://``, which is how those speak. Certificates are ``core.trust``'s.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import ssl
import time
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from libre_devops_helpers.core import brand, trust
from libre_devops_helpers.core.errors import ConfigError

PROXY_ENV = brand.env_var("PROXY_ADDRESS")
# Always direct: names and networks that are this machine, or its cloud host's metadata.
ALWAYS_DIRECT = ("localhost", "127.0.0.1", "::1", "169.254.169.254")
_DIRECT_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
)


@dataclass(frozen=True)
class NetworkSettings:
    """What the config file says about the network; the environment adds the rest."""

    proxy: str | None = None
    no_proxy: tuple[str, ...] = ()
    ca_bundle: Path | None = None


@dataclass(frozen=True)
class Route:
    """How a call to a URL goes: through ``proxy`` (None for direct), and why."""

    proxy: str | None
    source: str  # LDO_PROXY_ADDRESS, config, HTTPS_PROXY, system, no_proxy, local, none


class _Current:
    settings = NetworkSettings()


def configure(settings: NetworkSettings) -> None:
    """Set the rules for every call from now on (the CLI does this from the config file)."""
    _Current.settings = settings


def settings() -> NetworkSettings:
    return _Current.settings


def normalise_proxy(value: str, where: str) -> str:
    """``value`` as a proxy URL: ``127.0.0.1:3128`` becomes ``http://127.0.0.1:3128``."""
    text = value.strip()
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme not in {"http", "https"} or not parts.hostname or port == -1:
        raise ConfigError(
            f"{where}: {value!r} is not a proxy address",
            hint="use host:port or http://host:port, e.g. 127.0.0.1:3128 for cntlm",
        )
    return text.rstrip("/")


def split_list(value: object, where: str) -> tuple[str, ...]:
    """A ``no_proxy`` value: a comma-separated string, or a list of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise ConfigError(f"{where}: expected a comma-separated string or a list of strings")
    return tuple(item.strip() for item in items if item.strip())


def no_proxy(environ: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    """Every entry that sends a host direct: the config file's, then ``NO_PROXY``'s."""
    from_env = environ.get("NO_PROXY") or environ.get("no_proxy") or ""
    return tuple(dict.fromkeys([*_Current.settings.no_proxy, *split_list(from_env, "NO_PROXY")]))


def bypassed(host: str, entries: Iterable[str]) -> bool:
    """Whether ``host`` matches a ``no_proxy`` entry: ``*``, a name or ``.suffix``, a
    ``*.suffix``, an address, or a network such as ``10.0.0.0/8``. A port is ignored."""
    host = host.strip("[]").lower().rstrip(".")
    address = _address(host)
    for raw in entries:
        entry = raw.strip().lower()
        if not entry:
            continue
        if entry == "*":
            return True
        if "/" in entry and address is not None:
            try:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                pass
            continue
        entry = _without_port(entry).removeprefix("*").strip(".[]")
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _without_port(entry: str) -> str:
    if entry.startswith("["):  # [::1]:8080
        return entry.split("]", 1)[0] + "]"
    head, sep, tail = entry.rpartition(":")
    return head if sep and tail.isdigit() and ":" not in head else entry


def _address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def always_direct(host: str) -> bool:
    host = host.strip("[]").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    address = _address(host)
    return address is not None and any(address in network for network in _DIRECT_NETWORKS)


def configured(
    scheme: str = "https",
    *,
    environ: Mapping[str, str] = os.environ,
    system: Callable[[], Mapping[str, str]] = urllib.request.getproxies,
) -> Route:
    """The proxy the settings name for ``scheme``, before any host is considered."""
    explicit = environ.get(PROXY_ENV)
    if explicit and explicit.strip():
        return Route(normalise_proxy(explicit, PROXY_ENV), PROXY_ENV)
    if _Current.settings.proxy:
        return Route(_Current.settings.proxy, "config")
    for name in (f"{scheme}_proxy", "all_proxy"):
        value = environ.get(name.upper()) or environ.get(name)
        if value:
            return Route(normalise_proxy(value, name.upper()), name.upper())
    found = dict(system() or {})
    value = found.get(scheme) or found.get("all")
    if value:
        return Route(normalise_proxy(value, "the system proxy setting"), "system")
    return Route(None, "none")


def route(
    url: str,
    *,
    environ: Mapping[str, str] = os.environ,
    system: Callable[[], Mapping[str, str]] = urllib.request.getproxies,
    system_bypass: Callable[[str], object] = urllib.request.proxy_bypass,
) -> Route:
    """How a call to ``url`` goes, by the rules above."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if always_direct(host):
        return Route(None, "local")
    if bypassed(host, no_proxy(environ)):
        return Route(None, "no_proxy")
    found = configured(parts.scheme, environ=environ, system=system)
    if found.source == "system" and system_bypass(host):
        return Route(None, "no_proxy")
    return found


def requests_proxies(url: str) -> dict[str, str | None]:
    """``proxies`` for ``requests``. None means direct: requests drops it rather than
    falling back to the environment."""
    proxy = route(url).proxy
    return {"http": proxy, "https": proxy}


def ca_bundle() -> trust.Bundle:
    """The certificates every call verifies against (see ``core.trust``)."""
    return trust.resolve(_Current.settings.ca_bundle)


def subprocess_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """What another program (the Azure CLI) needs in its environment to follow the same
    rules: the proxy ldo would use, and the CA bundle, unless it already names one."""
    env: dict[str, str] = {}
    explicit = environ.get(PROXY_ENV)
    proxy = (
        normalise_proxy(explicit, PROXY_ENV) if explicit and explicit.strip() else None
    ) or _Current.settings.proxy
    if proxy:
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = proxy
        env["NO_PROXY"] = ",".join(dict.fromkeys([*ALWAYS_DIRECT, *no_proxy(environ)]))
    if not environ.get("REQUESTS_CA_BUNDLE"):
        # The same bundle ldo's own calls verify against, so az trusts exactly as ldo does.
        env["REQUESTS_CA_BUNDLE"] = ca_bundle().path
    return env


# Testing the way out ----------------------------------------------------------------------

# Where cntlm and Px listen unless told otherwise, and the port next to it.
LOCAL_PROXY_PORTS = (3128, 3129)


@dataclass(frozen=True)
class Probe:
    """One request's outcome: whether it got an expected answer, and what to do if not."""

    url: str
    route: Route
    ok: bool
    status: int | None
    detail: str
    hint: str | None = None
    elapsed: float = 0.0


def probe(
    url: str,
    *,
    expect: Iterable[int] = range(200, 300),
    session: requests.Session | None = None,
    timeout: float = 10.0,
    issuer: Callable[[str, int, str | None], str | None] | None = None,
    listening: Callable[[], str | None] | None = None,
) -> Probe:
    """GET ``url`` by the same rules as every call (proxy and certificates), unsigned.

    ``ok`` when the answer is in ``expect``; otherwise ``detail`` says what happened and
    ``hint`` what to try: the proxy's sign-in, a TLS-inspecting proxy's certificate, or
    a local cntlm or Px that could be used.
    """
    wanted = set(expect)
    how = route(url)
    bundle = ca_bundle()
    client = session or requests.Session()
    if session is None:
        client.trust_env = False
    started = time.monotonic()
    try:
        response = client.get(
            url,
            proxies={"http": how.proxy, "https": how.proxy},
            verify=bundle.path,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": f"{brand.COMMAND}-network-test"},
        )
    except requests.exceptions.SSLError as exc:
        parts = urlsplit(url)
        found = (issuer or peer_issuer)(parts.hostname or "", parts.port or 443, how.proxy)
        return Probe(
            url, how, False, None, _tls_detail(exc, found), _tls_hint(bundle), _since(started)
        )
    except requests.exceptions.ProxyError as exc:
        if "407" in str(exc):
            sign_in = "the proxy wants a sign-in of its own"
            return Probe(url, how, False, 407, sign_in, _sign_in_hint(how.proxy), _since(started))
        return Probe(
            url,
            how,
            False,
            None,
            f"cannot reach the proxy {how.proxy}",
            "is it running and listening there (cntlm, Px)? Check the address and port",
            _since(started),
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        detail = "timed out" if isinstance(exc, requests.exceptions.Timeout) else "no connection"
        hint = None
        if how.proxy is None:
            local = (listening or local_proxy_listening)()
            hint = f"this network may need a proxy: set HTTPS_PROXY or {PROXY_ENV}"
            if local:
                hint = (
                    f"something is listening on {local}, like cntlm or Px: try {PROXY_ENV}={local}"
                )
        return Probe(url, how, False, None, detail, hint, _since(started))
    elapsed = _since(started)
    status = response.status_code
    if status == 407:
        sign_in = "the proxy wants a sign-in of its own"
        return Probe(url, how, False, status, sign_in, _sign_in_hint(how.proxy), elapsed)
    ok = status in wanted
    return Probe(url, how, ok, status, f"HTTP {status}", None, elapsed)


def _sign_in_hint(proxy: str | None) -> str:
    if proxy and always_direct(urlsplit(proxy).hostname or ""):
        # Already a local proxy (cntlm, Px): it is the one failing to sign in upstream.
        return (
            f"the local proxy at {proxy} could not sign in to the corporate proxy: check its "
            "credentials and domain (for cntlm, 'cntlm -I -M https://graph.microsoft.com' "
            "tests them)"
        )
    return (
        "corporate proxies often want NTLM or Kerberos: run cntlm or Px, which sign in for "
        f"you, and set {PROXY_ENV} to where it listens, e.g. 127.0.0.1:3128"
    )


def _since(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _tls_detail(error: Exception, issuer_name: str | None) -> str:
    reason = str(error)
    for known in (
        "self-signed certificate in certificate chain",
        "self-signed certificate",
        "unable to get local issuer certificate",
        "certificate has expired",
        "Hostname mismatch",
    ):
        if known.lower() in reason.lower():
            reason = known
            break
    else:
        reason = "the certificate did not verify"
    return f"TLS: {reason}" + (
        f"; the certificate is issued by {issuer_name}" if issuer_name else ""
    )


def _tls_hint(bundle: trust.Bundle) -> str:
    if bundle.explicit:
        return (
            f"{bundle.explicit} names {bundle.path}, used as it is: add the proxy's root "
            f"certificate to it, or unset {bundle.explicit} to trust the OS store"
        )
    return (
        "a TLS-inspecting proxy? Its root certificate is not in this machine's store: ask IT "
        "for it, then install it there or name it with ca_bundle in the config file"
    )


def local_proxy_listening(ports: Iterable[int] = LOCAL_PROXY_PORTS) -> str | None:
    """``127.0.0.1:<port>`` for the first local proxy port something listens on, or None."""
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return f"127.0.0.1:{port}"
        except OSError:
            continue
    return None


def peer_issuer(host: str, port: int, proxy: str | None, *, timeout: float = 10.0) -> str | None:
    """Who issued the certificate ``host`` presents, through ``proxy`` when given: a
    TLS-inspecting proxy's own name shows here. None when it cannot be read."""
    try:
        if proxy:
            parts = urlsplit(proxy)
            if parts.scheme != "http":
                return None
            sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
            sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
            reply = b""
            while b"\r\n\r\n" not in reply and len(reply) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                reply += chunk
            if b" 200" not in reply.split(b"\r\n", 1)[0]:
                sock.close()
                return None
        else:
            sock = socket.create_connection((host, port), timeout=timeout)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
        return issuer_name(der) if der else None
    except (OSError, ValueError):
        return None


def issuer_name(der: bytes) -> str | None:
    """A certificate's issuer as ``Common Name (Organisation)``, read from its DER."""
    try:
        certificate = _der_children(der, 0, len(der))[0]
        tbs = _der_children(der, *certificate[1:])[0]
        fields = _der_children(der, *tbs[1:])
        # [0] version is optional: skip it, then serial and signature, to the issuer.
        start = 1 if fields[0][0] == 0xA0 else 0
        issuer = fields[start + 2]
        names: dict[str, str] = {}
        for rdn in _der_children(der, *issuer[1:]):
            for pair in _der_children(der, *rdn[1:]):
                oid, value = _der_children(der, *pair[1:])[:2]
                key = der[oid[1] : oid[2]]
                text = der[value[1] : value[2]]
                decoded = text.decode("utf-16-be" if value[0] == 0x1E else "utf-8", "replace")
                names[{b"\x55\x04\x03": "CN", b"\x55\x04\x0a": "O"}.get(key, "")] = decoded
        common, organisation = names.get("CN"), names.get("O")
        if common and organisation and organisation not in common:
            return f"{common} ({organisation})"
        return common or organisation
    except (IndexError, ValueError):
        return None


def _der_children(der: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    """Each element between ``start`` and ``end``: (tag, content start, content end)."""
    found = []
    position = start
    while position < end:
        tag = der[position]
        length = der[position + 1]
        position += 2
        if length & 0x80:
            size = length & 0x7F
            length = int.from_bytes(der[position : position + size], "big")
            position += size
        if position + length > end:
            raise ValueError("truncated DER")
        found.append((tag, position, position + length))
        position += length
    return found
