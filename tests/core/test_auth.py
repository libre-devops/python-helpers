from datetime import UTC, datetime, timedelta

from libre_devops_helpers.core.auth import (
    AccessToken,
    CachingTokenProvider,
    token_source,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class CountingProvider:
    def __init__(self, lifetime: timedelta) -> None:
        self.lifetime = lifetime
        self.calls = 0

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        self.calls += 1
        return AccessToken(f"t{self.calls}", NOW + self.lifetime, tenant_id, resource)


def test_tokens_are_reused_until_close_to_expiry():
    inner = CountingProvider(timedelta(hours=1))
    cache = CachingTokenProvider(inner, clock=lambda: NOW)
    assert cache.get_token("graph", "T").token == "t1"
    assert cache.get_token("graph", "t").token == "t1"  # tenant ids compare case-insensitively
    assert cache.get_token("mde", "T").token == "t2"
    assert inner.calls == 2


def test_a_token_inside_the_refresh_window_is_replaced():
    inner = CountingProvider(timedelta(minutes=2))
    cache = CachingTokenProvider(inner, clock=lambda: NOW)
    cache.get_token("graph", "T")
    cache.get_token("graph", "T")
    assert inner.calls == 2


def test_token_value_is_not_in_repr():
    token = AccessToken("secret-value", NOW, "T", "graph")
    assert "secret-value" not in repr(token)


def test_token_source_returns_the_bearer_string():
    source = token_source(CountingProvider(timedelta(hours=1)), "graph", "T")
    assert source() == "t1"


def test_invalidate_drops_only_that_token():
    provider = CountingProvider(timedelta(hours=1))
    cache = CachingTokenProvider(provider, clock=lambda: NOW)
    cache.get_token("https://graph.microsoft.com", "T")
    cache.get_token("https://management.azure.com/", "T")
    cache.invalidate("https://graph.microsoft.com", "t")  # tenant ids match case-insensitively
    assert cache.get_token("https://graph.microsoft.com", "T").token == "t3"
    assert cache.get_token("https://management.azure.com/", "T").token == "t2"


def test_a_bearer_token_refreshes_through_the_cache():
    provider = CountingProvider(timedelta(hours=1))
    bearer = token_source(CachingTokenProvider(provider, clock=lambda: NOW), "r", "T")
    assert bearer() == "t1"
    assert bearer() == "t1"
    bearer.refresh()
    assert bearer() == "t2"
    assert "t1" not in repr(bearer)


def test_refresh_is_harmless_on_a_provider_without_a_cache():
    provider = CountingProvider(timedelta(hours=1))
    bearer = token_source(provider, "r", "T")
    bearer.refresh()
    assert bearer() == "t1"
