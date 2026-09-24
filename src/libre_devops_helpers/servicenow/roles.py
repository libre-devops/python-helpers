"""What each ServiceNow feature needs: roles, since the instance's access controls decide.

``admin`` passes every access control, so it satisfies every requirement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

ADMIN = "admin"


@dataclass(frozen=True)
class RoleRequirement:
    """``feature`` needs any one of ``any_of`` (or admin)."""

    feature: str
    any_of: tuple[str, ...]

    def met_by(self, roles: Iterable[str]) -> bool:
        held = {role.casefold() for role in roles}
        return ADMIN in held or any(role.casefold() in held for role in self.any_of)
