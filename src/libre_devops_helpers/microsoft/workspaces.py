"""Naming a Log Analytics workspace three ways, and telling them apart.

A workspace has three names, and they are easy to mix up:

- its **Workspace ID**, a GUID on the workspace's Overview page, which the Log Analytics
  query API wants;
- its **resource id**, ``/subscriptions/.../providers/Microsoft.OperationalInsights/
  workspaces/NAME``, which Resource Manager wants (and the portal's JSON view shows);
- its **name**.

``workspace_ref`` takes any of them and says which it was, so a command can take whichever
a person has to hand, look the Workspace ID up when it needs to, and say what it found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.util import is_guid
from libre_devops_helpers.microsoft.resource_ids import (
    ResourceId,
    looks_like_resource_id,
    parse_resource_id,
)

WORKSPACE_TYPE = "Microsoft.OperationalInsights/workspaces"
WORKSPACE_HINT = (
    "give the workspace's Workspace ID (a GUID, on its Overview page), its resource id "
    "(/subscriptions/.../providers/Microsoft.OperationalInsights/workspaces/NAME), or its name"
)
# A workspace's name: 4 to 63 letters, digits and hyphens, not starting or ending with one.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{2,61}[A-Za-z0-9]")

Kind = Literal["workspace id", "resource id", "name"]


@dataclass(frozen=True)
class WorkspaceRef:
    """A workspace as someone named it: ``kind`` says which of its three names ``value`` is."""

    kind: Kind
    value: str
    resource_id: ResourceId | None = None


def workspace_ref(text: str) -> WorkspaceRef:
    """``text`` as a workspace's Workspace ID, resource id or name, whichever it is; an
    InputError that says what it looks like instead, when it is none of them."""
    value = text.strip()
    if is_guid(value):
        return WorkspaceRef("workspace id", value.lower())
    if looks_like_resource_id(value):
        found = parse_resource_id(value)
        if not found.is_type(WORKSPACE_TYPE):
            raise InputError(
                f"that is the resource id of a {found.type or 'tenant'}, not of a Log "
                f"Analytics workspace: {found.id!r}",
                hint=WORKSPACE_HINT,
            )
        return WorkspaceRef("resource id", found.id, found)
    if _NAME.fullmatch(value):
        return WorkspaceRef("name", value)
    raise InputError(f"not a Log Analytics workspace: {text!r}", hint=WORKSPACE_HINT)
