import pytest

from libre_devops_helpers.core import network
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


@pytest.mark.parametrize(
    ("address", "shown"),
    [
        ("http://alice:s3cret@proxy.corp.example:8080", "http://alice:***@proxy.corp.example:8080"),
        ("http://CORP%5Calice:p%40ss@[::1]:3128", "http://CORP%5Calice:***@[::1]:3128"),
        ("http://alice@proxy.corp.example:8080", "http://alice@proxy.corp.example:8080"),
        ("http://127.0.0.1:3129", "http://127.0.0.1:3129"),
        (None, None),
        ("", ""),
    ],
)
def test_a_proxy_password_is_redacted_for_showing(address, shown):
    assert network.redact(address) == shown


def test_a_route_never_shows_its_password():
    route = Route("http://alice:s3cret@proxy.corp.example:8080", "HTTPS_PROXY")
    assert route.shown == "http://alice:***@proxy.corp.example:8080"
    assert "s3cret" not in repr(route)
    assert route.proxy == "http://alice:s3cret@proxy.corp.example:8080"  # still used as it is


def test_a_bad_proxy_address_is_refused_without_its_password():
    with pytest.raises(ConfigError) as caught:
        network.normalise_proxy("alice:s3cret@proxy.corp.example:port", "HTTPS_PROXY")
    assert "s3cret" not in str(caught.value)
    assert "alice:***@" in str(caught.value)
