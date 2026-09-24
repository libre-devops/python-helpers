"""Access tokens and token providers.

A token provider is anything with ``get_token(resource, tenant_id)``. Each vendor layer
supplies its own credentials (``microsoft.auth`` for Entra ID), and its service modules
accept any provider, so none of them depends on where a token comes from.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AccessToken:
    """A bearer token. ``token`` is left out of repr so it cannot leak into logs."""

    token: str = field(repr=False)
    expires_on: datetime
    tenant_id: str
    resource: str

    def expires_within(self, window: timedelta, *, now: datetime | None = None) -> bool:
        """True when the token expires within ``window`` of ``now``."""
        return self.expires_on - (now or utc_now()) <= window


class TokenProvider(Protocol):
    """Anything that can produce an access token for a resource in a tenant."""

    def get_token(self, resource: str, tenant_id: str) -> AccessToken: ...


class CachingTokenProvider:
    """Wraps a provider and reuses each token until it is close to expiry.

    The cache is in memory only; tokens are never written to disk. It is safe to share
    between threads, and a token is fetched once even when several threads ask at once.
    """

    def __init__(
        self,
        inner: TokenProvider,
        *,
        refresh_before: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._inner = inner
        self._refresh_before = refresh_before
        self._clock = clock
        self._cache: dict[tuple[str, str], AccessToken] = {}
        self._lock = threading.Lock()

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        key = (resource, tenant_id.lower())
        with self._lock:
            cached = self._cache.get(key)
            if cached is None or cached.expires_within(self._refresh_before, now=self._clock()):
                cached = self._inner.get_token(resource, tenant_id)
                self._cache[key] = cached
            return cached

    def invalidate(self, resource: str, tenant_id: str) -> None:
        """Forget the cached token, so the next request fetches a new one."""
        with self._lock:
            self._cache.pop((resource, tenant_id.lower()), None)


class BearerToken:
    """A current bearer token each time it is called, as ApiClient expects.

    ``refresh`` drops the provider's cached token (when it caches), so the next call
    fetches a new one. ApiClient calls it once when an API answers 401.
    """

    def __init__(self, provider: TokenProvider, resource: str, tenant_id: str) -> None:
        self._provider = provider
        self._resource = resource
        self._tenant_id = tenant_id

    def __repr__(self) -> str:
        return f"BearerToken(resource={self._resource!r}, tenant_id={self._tenant_id!r})"

    def __call__(self) -> str:
        return self._provider.get_token(self._resource, self._tenant_id).token

    def refresh(self) -> None:
        invalidate = getattr(self._provider, "invalidate", None)
        if callable(invalidate):
            invalidate(self._resource, self._tenant_id)


def token_source(provider: TokenProvider, resource: str, tenant_id: str) -> BearerToken:
    """A zero-argument callable returning a current bearer token, as ApiClient expects."""
    return BearerToken(provider, resource, tenant_id)
