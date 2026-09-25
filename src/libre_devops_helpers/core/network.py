"""Corporate networks: which proxy each call goes through, and what it trusts.

Every HTTPS call this package makes, and every ``az`` the CLI runs, follows one set of
rules:

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

What the config file adds (``proxy``, ``no_proxy``, ``ca_bundle``) is a
``NetworkSettings``. ``configure`` sets the process's own, which the CLI does once from the
config file; a library user with two networks in one process gives each ``ApiClient`` its
own ``network_settings`` instead, and every function here takes ``settings`` for the same
reason. Without either, the settings are empty and the environment alone decides.

A proxy address may carry a password (``http://user:password@proxy:8080``). It is used as
it is, but never shown: anything written for a person goes through ``redact``, and a
``Route``'s repr is redacted too.
"""

from __future__ import annotations

import ipaddress
import os
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit

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

    @property
    def shown(self) -> str | None:
        """The proxy as it may be shown: without its password."""
        return redact(self.proxy)

    def __repr__(self) -> str:
        return f"Route(proxy={self.shown!r}, source={self.source!r})"


def redact(url: str | None) -> str | None:
    """``url`` safe to show: the password in ``http://user:password@host`` becomes ``***``.

    The user name stays, since it helps to see which account a proxy is given.
    """
    if not url:
        return url
    parts = urlsplit(url)
    userinfo, at, host = parts.netloc.rpartition("@")
    if not at or ":" not in userinfo:
        return url
    user = userinfo.split(":", 1)[0]
    return urlunsplit(parts._replace(netloc=f"{user}:***@{host}"))


class _Current:
    """The process's settings: what ``configure`` last set."""

    settings = NetworkSettings()


def configure(settings: NetworkSettings) -> None:
    """Set the process's settings, used by every call not given its own (the CLI does this
    once, from the config file)."""
    _Current.settings = settings


def settings() -> NetworkSettings:
    """The process's settings, as ``configure`` last set them."""
    return _Current.settings


def _chosen(given: NetworkSettings | None) -> NetworkSettings:
    return given if given is not None else _Current.settings


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
            f"{where}: {redact(text)!r} is not a proxy address",
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


def no_proxy(
    environ: Mapping[str, str] = os.environ, *, settings: NetworkSettings | None = None
) -> tuple[str, ...]:
    """Every entry that sends a host direct: the config file's, then ``NO_PROXY``'s."""
    from_env = environ.get("NO_PROXY") or environ.get("no_proxy") or ""
    from_config = _chosen(settings).no_proxy
    return tuple(dict.fromkeys([*from_config, *split_list(from_env, "NO_PROXY")]))


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
    """Whether ``host`` is this machine or a link-local address (such as the metadata endpoint)."""
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
    settings: NetworkSettings | None = None,
) -> Route:
    """The proxy the settings name for ``scheme``, before any host is considered."""
    explicit = environ.get(PROXY_ENV)
    if explicit and explicit.strip():
        return Route(normalise_proxy(explicit, PROXY_ENV), PROXY_ENV)
    from_config = _chosen(settings).proxy
    if from_config:
        return Route(from_config, "config")
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
    settings: NetworkSettings | None = None,
) -> Route:
    """How a call to ``url`` goes, by the rules above."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if always_direct(host):
        return Route(None, "local")
    if bypassed(host, no_proxy(environ, settings=settings)):
        return Route(None, "no_proxy")
    found = configured(parts.scheme, environ=environ, system=system, settings=settings)
    if found.source == "system" and system_bypass(host):
        return Route(None, "no_proxy")
    return found


def requests_proxies(url: str, settings: NetworkSettings | None = None) -> dict[str, str]:
    """``proxies`` for ``requests``, for a call to ``url``."""
    return requests_proxies_for(route(url, settings=settings))


def requests_proxies_for(how: Route) -> dict[str, str]:
    """``proxies`` for ``requests`` that send a call the way ``how`` says.

    Direct is a None for each scheme, not an empty mapping: requests drops a None rather
    than falling back to a proxy of its own (a session's, or the environment's). Its type
    hints allow only strings, hence the cast.
    """
    return cast("dict[str, str]", {"http": how.proxy, "https": how.proxy})


def ca_bundle(settings: NetworkSettings | None = None) -> trust.Bundle:
    """The certificates every call verifies against (see ``core.trust``)."""
    return trust.resolve(_chosen(settings).ca_bundle)


def subprocess_env(
    environ: Mapping[str, str] = os.environ, *, settings: NetworkSettings | None = None
) -> dict[str, str]:
    """What another program (the Azure CLI) needs in its environment to follow the same
    rules: the proxy ldo would use, and the CA bundle, unless it already names one.

    ``HTTPS_PROXY`` and the system setting reach it anyway; only the proxy ldo alone
    knows of (``LDO_PROXY_ADDRESS``, or the config file's) is added.
    """
    env: dict[str, str] = {}
    explicit = environ.get(PROXY_ENV)
    from_ldo = normalise_proxy(explicit, PROXY_ENV) if explicit and explicit.strip() else None
    proxy = from_ldo or _chosen(settings).proxy
    if proxy:
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = proxy
        direct = [*ALWAYS_DIRECT, *no_proxy(environ, settings=settings)]
        env["NO_PROXY"] = ",".join(dict.fromkeys(direct))
    if not environ.get("REQUESTS_CA_BUNDLE"):
        # The same bundle ldo's own calls verify against, so az trusts exactly as ldo does.
        env["REQUESTS_CA_BUNDLE"] = ca_bundle(settings).path
    return env
