"""The APIs this tool talks to, as a token sees them, and what features need from a token.

A ``Resource`` is an API: the URL a token is requested for and the ``aud`` values that
mean it. Resources are built per cloud. A ``Requirement`` is declared by a feature
module (``entra``, ``xdr``, ...) to say which scopes or roles its calls need, so core
checks tokens without knowing any feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.microsoft.clouds import PUBLIC, Cloud

# First-party application ids. They are the same in every cloud, and a token may carry
# one as its audience instead of the URL.
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
MDE_APP_ID = "fc780465-2017-40d4-a0c5-307022471b92"
ARM_APP_ID = "797f4846-ba00-4fd7-ba43-dac1f8f63013"
LOG_ANALYTICS_APP_ID = "ca7f3f0b-7d91-482c-8e09-c5d840d0eac5"
KEY_VAULT_APP_ID = "cfa8b339-82a2-471a-a3c9-0fc0be7a4093"


def normalise_audience(value: str) -> str:
    """Compare audiences case-insensitively and without a trailing slash."""
    return value.strip().rstrip("/").lower()


@dataclass(frozen=True)
class Resource:
    """An API as seen by a token.

    ``url`` is what is asked for when requesting a token. ``audiences`` are the ``aud``
    claim values that mean this API (normalised).
    """

    key: str
    url: str
    audiences: frozenset[str]
    description: str = ""


@dataclass(frozen=True)
class Requirement:
    """What one feature needs from a token for the resource called ``resource``.

    Every inner tuple of ``all_of`` must be satisfied, each by any one of its scopes or
    roles: ``(("Device.Read.All", "Directory.Read.All"),)`` needs either of the two.
    """

    feature: str
    resource: str
    all_of: tuple[tuple[str, ...], ...]


def _resource(key: str, url: str, *audiences: str, description: str) -> Resource:
    return Resource(
        key=key,
        url=url,
        audiences=frozenset(normalise_audience(value) for value in (url, *audiences)),
        description=description,
    )


def resources_for(cloud: Cloud) -> dict[str, Resource]:
    """Every API this tool can call in ``cloud``, keyed by resource key."""
    found = [
        _resource(
            "graph",
            cloud.graph_url,
            GRAPH_APP_ID,
            description="Microsoft Graph (Entra ID and Intune)",
        ),
        _resource(
            "arm",
            cloud.arm_url + "/",
            cloud.arm_classic_url,
            ARM_APP_ID,
            description="Azure Resource Manager",
        ),
        _resource(
            "loganalytics",
            cloud.log_analytics_url,
            LOG_ANALYTICS_APP_ID,
            description="Log Analytics query API",
        ),
        _resource(
            "keyvault",
            f"https://{cloud.keyvault_suffix}",
            KEY_VAULT_APP_ID,
            description="Key Vault data plane",
        ),
    ]
    if cloud.mde_url is not None:
        found.append(
            _resource(
                "mde",
                cloud.mde_url,
                "https://securitycenter.onmicrosoft.com/windowsatpservice",
                MDE_APP_ID,
                description="Defender for Endpoint API",
            )
        )
    return {resource.key: resource for resource in found}


# The public cloud's resources, for callers that do not deal in clouds.
RESOURCES: Mapping[str, Resource] = resources_for(PUBLIC)
GRAPH = RESOURCES["graph"]
MDE = RESOURCES["mde"]
ARM = RESOURCES["arm"]
LOG_ANALYTICS = RESOURCES["loganalytics"]
KEY_VAULT = RESOURCES["keyvault"]


def resolve_resource(value: str, cloud: Cloud = PUBLIC) -> Resource:
    """Look up a resource by key (``graph``, ``mde``, ...) or by an https URL.

    An unknown https URL is wrapped as an ad hoc resource whose only accepted audience
    is the URL itself.
    """
    known = resources_for(cloud)
    key = value.strip()
    if key.lower() in known:
        return known[key.lower()]
    if key.startswith("https://"):
        audience = normalise_audience(key)
        for resource in known.values():
            if audience in resource.audiences:
                return resource
        return Resource(key=key, url=key, audiences=frozenset({audience}))
    raise LdoError(
        f"unknown resource {value!r}",
        hint=f"use one of {', '.join(sorted(known))}, or an https:// resource URL",
    )
