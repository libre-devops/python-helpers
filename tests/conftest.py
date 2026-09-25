"""Settings for the whole suite."""

import pytest

from libre_devops_helpers.core.token_store import FILE_ENV


@pytest.fixture(autouse=True)
def private_token_cache(tmp_path_factory, monkeypatch):
    """Point the kept sign-in file at a temporary folder, so no test writes to your home."""
    folder = tmp_path_factory.mktemp("token-cache")
    monkeypatch.setenv(FILE_ENV, str(folder / "refresh-tokens.json"))


@pytest.fixture(autouse=True)
def plain_stderr():
    """Each test starts with plain output, whatever the last one used: the text log format's
    stderr, rows in the order they come, and colour left to the terminal."""
    from libre_devops_helpers.cli import render
    from libre_devops_helpers.core import colour

    def reset():
        render.structured_output(False)
        render.sort_rows(None)
        render.unique_rows(None)
        colour.use(None)

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def default_network(monkeypatch, tmp_path_factory):
    """No test builds a CA bundle in your home or follows your proxy: each uses the public
    roots as an explicit bundle, no proxy, and the network's default rules."""
    import requests.certs

    from libre_devops_helpers.core import network, trust

    monkeypatch.setenv("LDO_CA_BUNDLE", requests.certs.where())
    # A test that builds a combined bundle writes it here, never in your own cache.
    cache = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    for name in ("LDO_PROXY_ADDRESS", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    network.configure(network.NetworkSettings())
    trust.forget()
    yield
    network.configure(network.NetworkSettings())
    trust.forget()
