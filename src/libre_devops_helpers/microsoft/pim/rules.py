"""Read a PIM role management policy's rules into ``PimSettings``.

Azure resources (ARM ``effectiveRules``) and Graph (``policy.rules``) use the same rule
ids, such as ``Expiration_EndUser_Assignment`` for how long an activation may last, so
one reader serves all three areas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from libre_devops_helpers.microsoft.pim.models import Area, PimSettings


def settings_from_rules(
    area: Area, role: str, scope: str, rules: Iterable[Mapping[str, Any]]
) -> PimSettings:
    by_id = {str(rule.get("id") or ""): rule for rule in rules if isinstance(rule, Mapping)}
    activation = by_id.get("Expiration_EndUser_Assignment", {})
    enablement = by_id.get("Enablement_EndUser_Assignment", {})
    approval = by_id.get("Approval_EndUser_Assignment", {})
    context = by_id.get("AuthenticationContext_EndUser_Assignment", {})
    enabled = {str(item).casefold() for item in enablement.get("enabledRules") or []}
    setting = approval.get("setting") if isinstance(approval.get("setting"), Mapping) else {}
    return PimSettings(
        area=area,
        role=role,
        scope=scope,
        max_activation=str(activation.get("maximumDuration") or ""),
        requires_mfa="multifactorauthentication" in enabled,
        requires_justification="justification" in enabled,
        requires_ticket="ticketing" in enabled,
        requires_approval=setting.get("isApprovalRequired") is True,
        approvers=tuple(_approvers(setting)),
        authentication_context=str(context.get("claimValue") or "")
        if context.get("isEnabled") is True
        else "",
        eligible_expiry=_expiry(by_id.get("Expiration_Admin_Eligibility", {})),
        active_expiry=_expiry(by_id.get("Expiration_Admin_Assignment", {})),
        raw=tuple(by_id.values()),
    )


def _approvers(setting: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for stage in setting.get("approvalStages") or []:
        if not isinstance(stage, Mapping):
            continue
        for approver in stage.get("primaryApprovers") or []:
            if isinstance(approver, Mapping):
                found.append(
                    str(
                        approver.get("description")
                        or approver.get("userId")
                        or approver.get("groupId")
                        or approver.get("id")
                        or ""
                    )
                )
    return [name for name in found if name]


def _expiry(rule: Mapping[str, Any]) -> str:
    """``permanent allowed``, the maximum duration, or empty when the rule is absent."""
    if not rule:
        return ""
    if rule.get("isExpirationRequired") is False:
        return "permanent allowed"
    return str(rule.get("maximumDuration") or "required")
