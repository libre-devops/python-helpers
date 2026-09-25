"""PIM records, in one shape across Azure resources, Entra roles and PIM for Groups.

Each API names things its own way (ARM's ``properties``, Graph's ``roleDefinitionId`` or
``groupId`` and ``accessId``); the clients convert their replies into these, so the CLI
shows all three areas in one table.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Area = Literal["azure", "entra", "groups"]
AREAS: tuple[Area, ...] = ("azure", "entra", "groups")


@dataclass(frozen=True)
class PimAssignment:
    """A role someone is eligible for, or holds now.

    ``role`` is the role's name (for PIM for Groups, ``member`` or ``owner`` of the group).
    ``scope`` is where it applies: an ARM scope, a directory scope, or the group.
    ``member_type`` is ``Direct``, ``Group`` (through a group) or ``Inherited`` (from a
    scope above). ``assignment_type`` is ``Activated`` (through PIM) or ``Assigned``
    (standing) for active roles, and empty for eligible ones.
    """

    area: Area
    state: Literal["eligible", "active"]
    role: str
    scope: str
    principal_id: str
    principal_name: str
    member_type: str
    assignment_type: str
    starts: datetime | None
    ends: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def permanent(self) -> bool:
        """True when nothing ends it: standing access, the thing PIM exists to reduce."""
        return self.ends is None

    @property
    def activated(self) -> bool:
        """Whether the role is held because it was activated, rather than assigned outright."""
        return self.assignment_type.casefold() == "activated"


@dataclass(frozen=True)
class PimRequest:
    """A request to activate, assign or remove a role, and where it has got to."""

    area: Area
    id: str
    action: str
    status: str
    role: str
    scope: str
    principal_id: str
    principal_name: str
    justification: str
    created: datetime | None
    starts: datetime | None
    ends: datetime | None
    duration: str
    ticket: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def pending(self) -> bool:
        """Whether the request is waiting for an approver."""
        return self.status.casefold() == "pendingapproval"


@dataclass(frozen=True)
class PimSettings:
    """A role's PIM settings: what activating it takes, and how long it lasts."""

    area: Area
    role: str
    scope: str
    max_activation: str
    requires_mfa: bool
    requires_justification: bool
    requires_ticket: bool
    requires_approval: bool
    approvers: tuple[str, ...]
    authentication_context: str
    eligible_expiry: str
    active_expiry: str
    raw: tuple[Mapping[str, Any], ...] = field(default=(), compare=False, repr=False)
