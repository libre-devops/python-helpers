"""Azure resource ids, read by what each part is, never by counting slashes.

An Azure Resource Manager (ARM) resource id says where a resource sits::

    /subscriptions/{id}/resourceGroups/{group}/providers/{namespace}/{type}/{name}

A child resource goes on with ``/{type}/{name}`` pairs (a vault's secret, a server's
database), and an extension resource (a lock, a role assignment, a Defender assessment)
adds a second ``/providers/`` to the resource it is on. Subscriptions, resource groups,
management groups (``/providers/Microsoft.Management/managementGroups/{name}``) and
tenant-level resources are ids too.

An id is not the same thing as the ids some services give their resources as well: a Log
Analytics workspace has a resource id (the path above) and a Workspace ID (a GUID, which
its query API wants), and it is easy to hand one to something that wants the other.
``parse_resource_id`` says clearly when something is not a resource id, and what kind of
resource one names, so a caller can tell a person which one they gave.

Every part is checked as it is read (no empty parts, no ``.`` or ``..``, nothing a URL
treats specially), so an id that parses can go into a request path safely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import is_guid

# What a part of an id may hold: anything but a separator, a URL's special characters
# (query, fragment, escapes) or white space. Names are the service's to restrict further.
_PART = re.compile(r"[^/?#%\\\s]+")
_EXAMPLE = "/subscriptions/SUBSCRIPTION_ID/resourceGroups/GROUP/providers/NAMESPACE/TYPE/NAME"


@dataclass(frozen=True)
class ResourceId:
    """A parsed resource id. ``types`` and ``names`` are the resource's own, after its last
    ``/providers/NAMESPACE``, child types included; ``parent`` is the resource an extension
    resource is on (None for any other)."""

    id: str
    subscription: str = ""
    resource_group: str = ""
    management_group: str = ""
    namespace: str = ""
    types: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    parent: ResourceId | None = None

    @property
    def type(self) -> str:
        """The full resource type: ``Microsoft.KeyVault/vaults/secrets``; for a subscription,
        a resource group or a management group, the type ARM gives those."""
        if self.namespace:
            return "/".join([self.namespace, *self.types])
        if self.resource_group:
            return "Microsoft.Resources/resourceGroups"
        if self.subscription:
            return "Microsoft.Resources/subscriptions"
        return ""

    @property
    def name(self) -> str:
        """The resource's own name: the last one in the id."""
        if self.names:
            return self.names[-1]
        return self.resource_group or self.management_group or self.subscription

    @property
    def scope(self) -> str:
        """The id of what this sits in or on: the resource an extension is on; for any other
        resource, its resource group, else its subscription; for a resource group, its
        subscription. "" for a subscription, a management group, or a tenant-level resource."""
        if self.parent is not None:
            return self.parent.id
        subscription = f"/subscriptions/{self.subscription}"
        if not self.namespace:
            return subscription if self.resource_group else ""
        if self.resource_group:
            return f"{subscription}/resourceGroups/{self.resource_group}"
        return subscription if self.subscription else ""

    def as_dict(self) -> dict[str, Any]:
        """The id's parts, by the names Terraform's ``provider::azurerm::parse_resource_id``
        gives them, plus ``id`` and ``management_group_name``.

        ``resource_type`` is the last type alone (``subnets``), ``full_resource_type`` the
        namespace and every type (``Microsoft.Network/virtualNetworks/subnets``), and
        ``parent_resources`` each type above it with its name. ``resource_scope`` is what
        an extension resource is on (None for any other resource), as Terraform has it.
        """
        return {
            "id": self.id,
            "full_resource_type": self.type,
            "parent_resources": dict(zip(self.types[:-1], self.names[:-1], strict=True)),
            "resource_group_name": self.resource_group or None,
            "resource_name": self.name,
            "resource_provider": self.namespace or None,
            "resource_scope": self.parent.id if self.parent is not None else None,
            "resource_type": self.types[-1] if self.types else self.type.rsplit("/", 1)[-1],
            "subscription_id": self.subscription or None,
            "management_group_name": self.management_group or None,
        }

    def is_type(self, resource_type: str) -> bool:
        """Whether this is a ``resource_type`` (such as
        ``Microsoft.OperationalInsights/workspaces``), whatever the case."""
        return self.type.casefold() == resource_type.casefold()


def looks_like_resource_id(text: str) -> bool:
    """Whether ``text`` is written as a resource id is (its leading slash may be missing),
    before anything checks that it is one."""
    value = text.strip().strip("/").casefold()
    return value.startswith(("subscriptions/", "providers/"))


def parse_resource_id(text: str) -> ResourceId:
    """``text`` as a ResourceId, or an InputError saying what is wrong with it."""
    value = text.strip()
    if not looks_like_resource_id(value):
        raise InputError(
            f"not an Azure resource id: {text!r}",
            hint=f"a resource id starts /subscriptions/ or /providers/, e.g. {_EXAMPLE}",
        )
    parts = value.strip("/").split("/")
    for part in parts:
        if not _PART.fullmatch(part) or part in {".", ".."}:
            raise InputError(
                f"not an Azure resource id: {text!r} (the part {part!r} cannot be in one)"
            )
    return _read(parts, "/" + "/".join(parts), text)


def try_parse_resource_id(text: str) -> ResourceId | None:
    """``text`` as a ResourceId, or None when it is not one: for reading ids from an API,
    where an odd one should not fail a whole listing."""
    try:
        return parse_resource_id(text)
    except InputError:
        return None


def _read(parts: list[str], whole: str, given: str) -> ResourceId:
    """The id, part by part: a subscription, a resource group, then each ``providers``
    section, the last of which is the resource itself (the others, what it extends)."""
    subscription = resource_group = ""
    index = 0
    if parts[0].casefold() == "subscriptions":
        subscription = _subscription(parts, given)
        index = 2
        if len(parts) > index and parts[index].casefold() == "resourcegroups":
            resource_group = _value(parts, index, given)
            index += 2
    sections = _provider_sections(parts[index:], given)
    management_group = _management_group(sections[0]) if sections else ""
    resource = ResourceId(whole, subscription, resource_group, management_group)
    parent: ResourceId | None = None
    for namespace, pairs in sections:
        index += 2 + 2 * len(pairs)
        resource = ResourceId(
            "/" + "/".join(parts[:index]),
            subscription,
            resource_group,
            management_group,
            namespace,
            tuple(kind for kind, _ in pairs),
            tuple(name for _, name in pairs),
            parent,
        )
        parent = resource
    return resource


def _provider_sections(parts: list[str], given: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """``providers/NAMESPACE/TYPE/NAME[/TYPE/NAME...]``, once or more (extensions)."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    index = 0
    while index < len(parts):
        if parts[index].casefold() != "providers" or index + 1 >= len(parts):
            raise InputError(
                f"not an Azure resource id: {given!r} (expected providers/NAMESPACE at "
                f"{'/'.join(parts[index:]) or 'the end'})",
                hint=f"e.g. {_EXAMPLE}",
            )
        namespace = parts[index + 1]
        index += 2
        pairs: list[tuple[str, str]] = []
        while index < len(parts) and parts[index].casefold() != "providers":
            if index + 1 >= len(parts):
                raise InputError(
                    f"not an Azure resource id: {given!r} (the type {parts[index]!r} has no name)"
                )
            pairs.append((parts[index], parts[index + 1]))
            index += 2
        if not pairs:
            raise InputError(f"not an Azure resource id: {given!r} ({namespace} names no type)")
        sections.append((namespace, pairs))
    return sections


def _subscription(parts: list[str], given: str) -> str:
    subscription = _value(parts, 0, given)
    if not is_guid(subscription):
        raise InputError(f"not an Azure resource id: {given!r} ({subscription!r} is not a GUID)")
    return subscription.lower()


def _value(parts: list[str], index: int, given: str) -> str:
    if index + 1 >= len(parts):
        raise InputError(f"not an Azure resource id: {given!r} ({parts[index]} has no value)")
    return parts[index + 1]


def _management_group(section: tuple[str, list[tuple[str, str]]]) -> str:
    """The management group an id starts with (``providers/Microsoft.Management/
    managementGroups/NAME``), else empty."""
    namespace, pairs = section
    if namespace.casefold() == "microsoft.management" and pairs[0][0].casefold() == (
        "managementgroups"
    ):
        return pairs[0][1]
    return ""
