import base64
import contextlib
import socket
import ssl
import threading

import pytest
import requests
import trustme

from fakes.certificates import TEST_CA
from libre_devops_helpers.core import network, trust
from libre_devops_helpers.core import probe as reach

GRAPH = "https://graph.microsoft.com/v1.0/me"


class FakeSession:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        response = requests.Response()
        response.status_code = self.outcome
        return response


def probe(outcome, **options):
    return reach.probe(
        "https://graph.microsoft.com/v1.0/",
        session=FakeSession(outcome),
        issuer=lambda host, port, proxy: "Contoso Inspection CA",
        listening=lambda: options.get("listening"),
        **{key: value for key, value in options.items() if key != "listening"},
    )


def test_a_2xx_is_a_pass_and_anything_else_is_named():
    assert probe(200).ok
    assert probe(401).ok is False
    assert probe(401, expect=(200, 401)).ok
    assert probe(404).detail == "HTTP 404"


def test_a_tls_failure_names_the_issuer_and_how_to_trust_it(monkeypatch):
    monkeypatch.setattr(network, "ca_bundle", lambda: trust.Bundle("/cache/ca-bundle.pem", None))
    error = requests.exceptions.SSLError("certificate verify failed: self-signed certificate")
    result = probe(error)
    assert result.detail == (
        "TLS: self-signed certificate; the certificate is issued by Contoso Inspection CA"
    )
    assert "ca_bundle" in (result.hint or "")


def test_a_tls_failure_with_an_explicit_bundle_says_to_add_the_root_or_unset_it(monkeypatch):
    result = probe(requests.exceptions.SSLError("unable to get local issuer certificate"))
    assert "LDO_CA_BUNDLE names" in (result.hint or "")  # the tests' own explicit bundle


def test_a_proxy_that_wants_ntlm_points_at_cntlm(monkeypatch):
    result = probe(requests.exceptions.ProxyError("Tunnel connection failed: 407 Proxy Auth"))
    assert (result.status, result.ok) == (407, False)
    assert "run cntlm or Px" in (result.hint or "")
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    local = probe(407)
    assert "could not sign in to the corporate proxy" in (local.hint or "")


def test_a_proxy_that_is_not_there_is_named(monkeypatch):
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    result = probe(requests.exceptions.ProxyError("Cannot connect to proxy"))
    assert result.detail == "cannot reach the proxy http://127.0.0.1:3129"


def test_no_way_out_suggests_a_local_proxy_that_is_listening():
    lost = probe(requests.exceptions.ConnectTimeout("timed out"))
    assert lost.detail == "timed out"
    assert "may need a proxy" in (lost.hint or "")
    found = probe(requests.exceptions.ConnectionError("refused"), listening="127.0.0.1:3129")
    assert found.hint == (
        "something is listening on 127.0.0.1:3129, like cntlm or Px: "
        "try LDO_PROXY_ADDRESS=127.0.0.1:3129"
    )


def test_a_probe_follows_the_same_proxy_and_bundle_as_every_call(monkeypatch):
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    session = FakeSession(200)
    reach.probe(GRAPH, session=session)
    sent = session.calls[0]
    assert sent["proxies"] == {"http": "http://127.0.0.1:3129", "https": "http://127.0.0.1:3129"}
    assert sent["verify"] == network.ca_bundle().path
    assert sent["allow_redirects"] is False


def test_the_issuer_is_read_from_the_certificate():
    der = ssl.PEM_cert_to_DER_cert(TEST_CA)
    assert reach.issuer_name(der) == "Contoso Test Inspection CA"
    assert reach.issuer_name(b"\x30\x03\x02\x01") is None


def test_a_local_listener_is_found_on_the_ports_cntlm_and_px_use():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert reach.local_proxy_listening((port,)) == f"127.0.0.1:{port}"
    assert reach.local_proxy_listening((port,)) is None


def test_an_issuer_that_cannot_be_read_is_none():
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        closed = spare.getsockname()[1]
    assert reach.peer_issuer("127.0.0.1", closed, None, timeout=1) is None
    assert reach.peer_issuer("example.com", 443, "https://proxy:443") is None


def test_a_proxy_password_is_never_in_what_is_shown(monkeypatch):
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "http://alice:s3cret@127.0.0.1:3129")
    missing = probe(requests.exceptions.ProxyError("Cannot connect to proxy"))
    assert missing.detail == "cannot reach the proxy http://alice:***@127.0.0.1:3129"
    refused = probe(407)
    assert "s3cret" not in (refused.hint or "")
    assert "alice:***@127.0.0.1:3129" in (refused.hint or "")
    assert "s3cret" not in repr(refused)
    # The real address, password and all, is still what the request goes through.
    session = FakeSession(200)
    reach.probe(GRAPH, session=session)
    assert session.calls[0]["proxies"]["https"] == "http://alice:s3cret@127.0.0.1:3129"


# A TLS-inspecting proxy, for real: a local server presenting a certificate issued by a
# throwaway authority, reached directly or through a CONNECT tunnel.


@pytest.fixture
def inspection_ca():
    return trustme.CA(organization_name="Contoso Inspection")


def serve_once(handle) -> int:
    """Accept one connection on a free local port, in a thread, and pass it to ``handle``."""
    server = socket.create_server(("127.0.0.1", 0))

    def run():
        with server:
            connection, _ = server.accept()
            # The client hangs up as soon as it has the certificate.
            with connection, contextlib.suppress(OSError):
                handle(connection)

    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1]


def present_certificate(ca, connection) -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1", "graph.microsoft.com").configure_cert(context)
    with context.wrap_socket(connection, server_side=True) as tls:
        tls.recv(1)


def test_the_issuer_is_read_from_the_server_itself(inspection_ca):
    port = serve_once(lambda connection: present_certificate(inspection_ca, connection))
    assert reach.peer_issuer("127.0.0.1", port, None, timeout=5) == "Contoso Inspection"


def test_the_issuer_is_read_through_a_proxy_tunnel_signed_as_the_address_says(inspection_ca):
    asked = []

    def proxy(connection):
        request = b""
        while b"\r\n\r\n" not in request:
            request += connection.recv(4096)
        asked.append(request.decode())
        connection.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        present_certificate(inspection_ca, connection)

    port = serve_once(proxy)
    address = f"http://alice:s%40cret@127.0.0.1:{port}"
    assert reach.peer_issuer("graph.microsoft.com", 443, address, timeout=5) == (
        "Contoso Inspection"
    )
    request = asked[0]
    assert request.startswith("CONNECT graph.microsoft.com:443 HTTP/1.1\r\n")
    signed = base64.b64encode(b"alice:s@cret").decode()
    assert f"Proxy-Authorization: Basic {signed}\r\n" in request


def test_a_proxy_that_refuses_the_tunnel_gives_no_issuer():
    def proxy(connection):
        connection.recv(4096)
        connection.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")

    port = serve_once(proxy)
    assert reach.peer_issuer("example.com", 443, f"http://127.0.0.1:{port}", timeout=5) is None


def test_a_certificate_without_a_common_name_is_named_by_its_organisation(inspection_ca):
    der = ssl.PEM_cert_to_DER_cert(inspection_ca.cert_pem.bytes().decode())
    assert reach.issuer_name(der) == "Contoso Inspection"
    assert reach.issuer_name(b"") is None
    assert reach.issuer_name(b"\x30\x00") is None  # a certificate with nothing in it


def test_many_urls_are_probed_at_once_and_come_back_in_order(monkeypatch):
    asked = []

    def probe(url, *, expect, timeout):
        asked.append((url, tuple(expect), timeout))
        return reach.Probe(url, network.Route(None, "none"), True, 200, "HTTP 200")

    monkeypatch.setattr(reach, "probe", probe)
    targets = [(f"https://host{n}.example/", (200,)) for n in range(5)]
    found = reach.probe_all(targets, timeout=3)
    assert [item.url for item in found] == [url for url, _ in targets]
    assert sorted(asked) == [(url, (200,), 3) for url, _ in targets]
    assert reach.probe_all([]) == []
