"""Testing the way out: one request to a URL, by the network's rules, and what went wrong.

``probe`` sends an unsigned GET the way every call goes (``core.network``'s proxy and
``core.trust``'s certificates) and turns a failure into something a person can act on:

- the proxy wants a sign-in of its own (HTTP 407): run cntlm or Px;
- the proxy is not there: is it running, on that port?
- no way out at all: this network may need a proxy, and one may be listening locally;
- the certificate did not verify: a TLS-inspecting proxy, named by its certificate's
  issuer, whose root the machine does not trust yet.

To name that issuer, ``peer_issuer`` reads the certificate the server (or the proxy in
the middle) presents, without verifying it, and ``issuer_name`` reads the issuer out of
its bytes. They only ever describe a certificate for a hint; nothing here decides what
is trusted.
"""

from __future__ import annotations

import base64
import socket
import ssl
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import SplitResult, unquote, urlsplit

import requests

from libre_devops_helpers.core import brand, network, trust

# Where cntlm and Px listen unless told otherwise, and the port next to it.
LOCAL_PROXY_PORTS = (3128, 3129)
# The most of a proxy's answer to CONNECT that is read before giving up on it.
_MAX_REPLY = 65536


@dataclass(frozen=True)
class Probe:
    """One request's outcome: whether it got an expected answer, and what to do if not."""

    url: str
    route: network.Route
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
    ``hint`` what to try. ``issuer`` and ``listening`` stand in for ``peer_issuer`` and
    ``local_proxy_listening`` in tests.
    """
    how = network.route(url)
    bundle = network.ca_bundle()
    started = time.monotonic()
    try:
        response = _get(url, how, bundle, session, timeout)
    except requests.exceptions.SSLError as exc:
        parts = urlsplit(url)
        found = (issuer or peer_issuer)(parts.hostname or "", parts.port or 443, how.proxy)
        return Probe(
            url, how, False, None, _tls_detail(exc, found), _tls_hint(bundle), _since(started)
        )
    except requests.exceptions.ProxyError as exc:
        if "407" in str(exc):
            return _needs_proxy_sign_in(url, how, started)
        detail = f"cannot reach the proxy {how.shown}"
        check = "is it running and listening there (cntlm, Px)? Check the address and port"
        return Probe(url, how, False, None, detail, check, _since(started))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        detail = "timed out" if isinstance(exc, requests.exceptions.Timeout) else "no connection"
        hint: str | None = None
        if not how.proxy:
            hint = _no_way_out_hint((listening or local_proxy_listening)())
        return Probe(url, how, False, None, detail, hint, _since(started))
    status = response.status_code
    if status == 407:
        return _needs_proxy_sign_in(url, how, started)
    return Probe(url, how, status in set(expect), status, f"HTTP {status}", None, _since(started))


def probe_all(
    targets: Sequence[tuple[str, Iterable[int]]], *, timeout: float = 10.0, workers: int = 8
) -> list[Probe]:
    """``probe`` each (url, expected statuses), ``workers`` at a time, in the order given."""
    if not targets:
        return []

    def one(target: tuple[str, Iterable[int]]) -> Probe:
        url, expect = target
        return probe(url, expect=expect, timeout=timeout)

    with ThreadPoolExecutor(max_workers=min(workers, len(targets))) as pool:
        return list(pool.map(one, targets))


def _get(
    url: str,
    how: network.Route,
    bundle: trust.Bundle,
    session: requests.Session | None,
    timeout: float,
) -> requests.Response:
    """The GET itself, through ``how``'s proxy, on ``session`` or a session of its own."""
    client = session or requests.Session()
    if session is None:
        client.trust_env = False  # proxies and certificates come from core.network alone
    try:
        return client.get(
            url,
            proxies=network.requests_proxies_for(how),
            verify=bundle.path,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": f"{brand.COMMAND}-network-test"},
        )
    finally:
        if session is None:
            client.close()


def _needs_proxy_sign_in(url: str, how: network.Route, started: float) -> Probe:
    detail = "the proxy wants a sign-in of its own"
    return Probe(url, how, False, 407, detail, _sign_in_hint(how.proxy), _since(started))


def _sign_in_hint(proxy: str | None) -> str:
    if proxy and network.always_direct(urlsplit(proxy).hostname or ""):
        # Already a local proxy (cntlm, Px): it is the one failing to sign in upstream.
        return (
            f"the local proxy at {network.redact(proxy)} could not sign in to the corporate "
            "proxy: check its credentials and domain (for cntlm, "
            "'cntlm -I -M https://graph.microsoft.com' tests them)"
        )
    return (
        "corporate proxies often want NTLM or Kerberos: run cntlm or Px, which sign in for "
        f"you, and set {network.PROXY_ENV} to where it listens, e.g. 127.0.0.1:3128"
    )


def _no_way_out_hint(local: str | None) -> str:
    if local:
        return (
            f"something is listening on {local}, like cntlm or Px: try {network.PROXY_ENV}={local}"
        )
    return f"this network may need a proxy: set HTTPS_PROXY or {network.PROXY_ENV}"


def _since(started: float) -> float:
    return round(time.monotonic() - started, 3)


# What OpenSSL says when a certificate fails, shortened to the part a person needs.
_TLS_REASONS = (
    "self-signed certificate in certificate chain",
    "self-signed certificate",
    "unable to get local issuer certificate",
    "certificate has expired",
    "Hostname mismatch",
)


def _tls_detail(error: Exception, issuer: str | None) -> str:
    said = str(error).lower()
    reason = next(
        (known for known in _TLS_REASONS if known.lower() in said),
        "the certificate did not verify",
    )
    return f"TLS: {reason}" + (f"; the certificate is issued by {issuer}" if issuer else "")


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


# Reading who issued a certificate -----------------------------------------------------------


def peer_issuer(host: str, port: int, proxy: str | None, *, timeout: float = 10.0) -> str | None:
    """Who issued the certificate ``host`` presents, through ``proxy`` when given.

    Behind a TLS-inspecting proxy that is the proxy's own certificate authority, which is
    the name a person needs to ask IT for. The certificate is read without verifying it,
    since verifying it is what just failed, and nothing is sent over the connection.
    None when it cannot be read.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # to read the certificate, not to trust it
    try:
        with (
            _connect(host, port, proxy, timeout) as connection,
            context.wrap_socket(connection, server_hostname=host) as tls,
        ):
            der = tls.getpeercert(binary_form=True)
    except (OSError, ValueError):
        return None
    return issuer_name(der) if der else None


def _connect(host: str, port: int, proxy: str | None, timeout: float) -> socket.socket:
    """A connection to ``host:port``: direct, or a tunnel through an http ``proxy``."""
    if not proxy:
        return socket.create_connection((host, port), timeout=timeout)
    parts = urlsplit(proxy)
    if parts.scheme != "http":
        raise ConnectionError("only an http proxy can be tunnelled through here")
    connection = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
    try:
        connection.sendall(_connect_request(host, port, parts))
        if _reply_status(connection) != 200:
            raise ConnectionError("the proxy refused the tunnel")
    except OSError:
        connection.close()
        raise
    return connection


def _connect_request(host: str, port: int, proxy: SplitResult) -> bytes:
    """The CONNECT that opens a tunnel, signed with the proxy address's user and password
    when it has them, as requests signs its own."""
    lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if proxy.username:
        pair = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}".encode()
        lines.append(f"Proxy-Authorization: Basic {base64.b64encode(pair).decode('ascii')}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def _reply_status(connection: socket.socket) -> int | None:
    """The status code of the proxy's answer (``HTTP/1.1 200 Connection established``)."""
    reply = b""
    while b"\r\n\r\n" not in reply and len(reply) < _MAX_REPLY:
        chunk = connection.recv(4096)
        if not chunk:
            break
        reply += chunk
    words = reply.split(b"\r\n", 1)[0].split()
    return int(words[1]) if len(words) > 1 and words[1].isdigit() else None


# A certificate is DER: ASN.1 written as nested elements, each a tag byte, a length, then
# that many bytes of content. RFC 5280 gives the shape, of which only this much is read:
#
#   Certificate    ::= SEQUENCE { tbsCertificate, signatureAlgorithm, signatureValue }
#   TBSCertificate ::= SEQUENCE { [0] version OPTIONAL, serialNumber, signature, issuer, ... }
#   Name           ::= SEQUENCE OF SET OF SEQUENCE { type OBJECT IDENTIFIER, value string }
_VERSION_TAG = 0xA0  # the [0] that holds an explicit version
_COMMON_NAME = b"\x55\x04\x03"  # the OID 2.5.4.3, as DER writes it
_ORGANISATION = b"\x55\x04\x0a"  # 2.5.4.10
_BMP_STRING = 0x1E  # a string in UTF-16 (big-endian); the other string types are UTF-8 safe


class _Element(NamedTuple):
    """One DER element: its tag, and where its content starts and ends in the bytes."""

    tag: int
    start: int
    end: int


def issuer_name(der: bytes) -> str | None:
    """A certificate's issuer as ``Common Name (Organisation)``, from its DER bytes.

    None when the bytes are not a certificate.
    """
    try:
        certificate = _children(der)[0]
        tbs = _children(der, certificate)[0]
        fields = _children(der, tbs)
        if fields[0].tag == _VERSION_TAG:
            fields = fields[1:]
        _serial, _signature, issuer = fields[:3]
        names = dict(_attributes(der, issuer))
    except (IndexError, ValueError):
        return None
    common, organisation = names.get(_COMMON_NAME), names.get(_ORGANISATION)
    if common and organisation and organisation not in common:
        return f"{common} ({organisation})"
    return common or organisation


def _attributes(der: bytes, name: _Element) -> Iterator[tuple[bytes, str]]:
    """Each (OID, text) in a Name: a sequence of sets, each of (OID, value) pairs."""
    for relative in _children(der, name):
        for pair in _children(der, relative):
            oid, value = _children(der, pair)[:2]
            encoding = "utf-16-be" if value.tag == _BMP_STRING else "utf-8"
            yield der[oid.start : oid.end], der[value.start : value.end].decode(encoding, "replace")


def _children(der: bytes, parent: _Element | None = None) -> list[_Element]:
    """The elements inside ``parent`` (at the top of ``der`` when None), in order.

    A length under 128 is that one byte. Otherwise its low seven bits say how many of the
    bytes after it hold the length, most significant first.
    """
    position, end = (0, len(der)) if parent is None else (parent.start, parent.end)
    found = []
    while position < end:
        tag, length = der[position], der[position + 1]
        position += 2
        if length & 0x80:
            size = length & 0x7F
            length = int.from_bytes(der[position : position + size], "big")
            position += size
        if position + length > end:
            raise ValueError("truncated DER")
        found.append(_Element(tag, position, position + length))
        position += length
    return found
