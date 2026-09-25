import socket
import ssl

import pytest
import requests

from fakes.certificates import TEST_CA
from libre_devops_helpers.core import network, trust
from libre_devops_helpers.core.errors import ConfigError
from libre_devops_helpers.core.network import NetworkSettings, Route

GRAPH = "https://graph.microsoft.com/v1.0/me"
NO_SYSTEM = {"system": dict, "system_bypass": lambda host: False}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1:3129", "http://127.0.0.1:3129"),
        ("http://proxy.corp.example:8080/", "http://proxy.corp.example:8080"),
        ("https://proxy.corp.example", "https://proxy.corp.example"),
        ("http://user:pass@proxy:3128", "http://user:pass@proxy:3128"),
    ],
)
def test_proxy_addresses_default_to_http(value, expected):
    assert network.normalise_proxy(value, "proxy") == expected


@pytest.mark.parametrize("value", ["socks5://proxy:1080", "http://", "proxy:notaport", "://x"])
def test_bad_proxy_addresses_are_refused_with_an_example(value):
    with pytest.raises(ConfigError) as caught:
        network.normalise_proxy(value, "proxy")
    assert "127.0.0.1:3128" in (caught.value.hint or "")


def test_no_proxy_is_a_string_or_a_list():
    assert network.split_list("a, .b,,c ", "no_proxy") == ("a", ".b", "c")
    assert network.split_list(["a", " b "], "no_proxy") == ("a", "b")
    assert network.split_list(None, "no_proxy") == ()
    with pytest.raises(ConfigError):
        network.split_list([1], "no_proxy")


@pytest.mark.parametrize(
    ("host", "entries", "expected"),
    [
        ("graph.microsoft.com", ["*"], True),
        ("a.corp.example", [".corp.example"], True),
        ("corp.example", [".corp.example"], True),
        ("a.corp.example", ["*.corp.example"], True),
        ("a.corp.example", ["corp.example"], True),
        ("corp.example.evil.com", ["corp.example"], False),  # a suffix of labels, not text
        ("notcorp.example", ["corp.example"], False),
        ("proxy.corp", ["proxy.corp:8080"], True),
        ("10.1.2.3", ["10.0.0.0/8"], True),
        ("11.1.2.3", ["10.0.0.0/8"], False),
        ("::1", ["[::1]:8080"], True),
        ("Graph.Microsoft.com.", ["graph.microsoft.com"], True),
    ],
)
def test_no_proxy_entries_match_like_other_tools(host, entries, expected):
    assert network.bypassed(host, entries) is expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("app.localhost", True),
        ("127.0.0.5", True),
        ("169.254.169.254", True),
        ("::1", True),
        ("fe80::1", True),
        ("10.0.0.1", False),
        ("graph.microsoft.com", False),
    ],
)
def test_this_machine_and_the_metadata_endpoint_never_use_a_proxy(host, expected):
    assert network.always_direct(host) is expected


def test_the_proxy_comes_from_the_first_setting_that_names_one():
    network.configure(NetworkSettings(proxy="http://config:3128"))
    env = {"LDO_PROXY_ADDRESS": "127.0.0.1:3129", "HTTPS_PROXY": "http://env:8080"}
    assert network.route(GRAPH, environ=env, **NO_SYSTEM) == Route(
        "http://127.0.0.1:3129", "LDO_PROXY_ADDRESS"
    )
    del env["LDO_PROXY_ADDRESS"]
    assert network.route(GRAPH, environ=env, **NO_SYSTEM) == Route("http://config:3128", "config")
    network.configure(NetworkSettings())
    assert network.route(GRAPH, environ=env, **NO_SYSTEM) == Route("http://env:8080", "HTTPS_PROXY")
    all_proxy = {"all_proxy": "env:1"}
    assert network.route(GRAPH, environ=all_proxy, **NO_SYSTEM).source == "ALL_PROXY"
    system = {"system": lambda: {"https": "http://os:8080"}, "system_bypass": lambda host: False}
    assert network.route(GRAPH, environ={}, **system) == Route("http://os:8080", "system")
    assert network.route(GRAPH, environ={}, **NO_SYSTEM) == Route(None, "none")


def test_local_hosts_and_no_proxy_go_direct_whatever_the_proxy():
    env = {"LDO_PROXY_ADDRESS": "127.0.0.1:3129", "NO_PROXY": ".corp.example"}
    network.configure(NetworkSettings(no_proxy=("graph.microsoft.com",)))
    assert network.route("http://169.254.169.254/metadata", environ=env) == Route(None, "local")
    assert network.route(GRAPH, environ=env) == Route(None, "no_proxy")
    assert network.route("https://it.corp.example", environ=env) == Route(None, "no_proxy")
    system = {"system": lambda: {"https": "http://os:8080"}, "system_bypass": lambda host: True}
    assert network.route("https://intranet", environ={}, **system) == Route(None, "no_proxy")


def test_requests_is_told_direct_explicitly_so_it_cannot_fall_back(monkeypatch):
    assert network.requests_proxies(GRAPH) == {"http": None, "https": None}
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    assert network.requests_proxies(GRAPH) == {
        "http": "http://127.0.0.1:3129",
        "https": "http://127.0.0.1:3129",
    }


def test_the_azure_cli_gets_the_same_proxy_and_bundle(monkeypatch):
    bundle = network.ca_bundle().path
    assert network.subprocess_env({}) == {"REQUESTS_CA_BUNDLE": bundle}
    env = network.subprocess_env({"LDO_PROXY_ADDRESS": "127.0.0.1:3129", "NO_PROXY": ".corp"})
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://127.0.0.1:3129"
    assert env["NO_PROXY"].split(",") == [
        "localhost",
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        ".corp",
    ]
    # A bundle the person named already reaches az; it is never overridden.
    assert "REQUESTS_CA_BUNDLE" not in network.subprocess_env({"REQUESTS_CA_BUNDLE": "/x.pem"})


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
    return network.probe(
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
    network.probe(GRAPH, session=session)
    sent = session.calls[0]
    assert sent["proxies"] == {"http": "http://127.0.0.1:3129", "https": "http://127.0.0.1:3129"}
    assert sent["verify"] == network.ca_bundle().path
    assert sent["allow_redirects"] is False


def test_the_issuer_is_read_from_the_certificate():
    der = ssl.PEM_cert_to_DER_cert(TEST_CA)
    assert network.issuer_name(der) == "Contoso Test Inspection CA"
    assert network.issuer_name(b"\x30\x03\x02\x01") is None


def test_a_local_listener_is_found_on_the_ports_cntlm_and_px_use():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert network.local_proxy_listening((port,)) == f"127.0.0.1:{port}"
    assert network.local_proxy_listening((port,)) is None


def test_an_issuer_that_cannot_be_read_is_none():
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        closed = spare.getsockname()[1]
    assert network.peer_issuer("127.0.0.1", closed, None, timeout=1) is None
    assert network.peer_issuer("example.com", 443, "https://proxy:443") is None
