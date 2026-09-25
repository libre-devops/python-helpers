"""Reads Defender XDR custom detection rules through Microsoft Graph.

The API is ``security/rules/detectionRules``, which is still beta only, so that is the
version used. It needs ``CustomDetection.Read.All``: the Azure CLI's Graph token never
carries it unless an admin consents it for the Azure CLI's own app.
"""

from __future__ import annotations

from urllib.parse import quote

from libre_devops_helpers.core.errors import AmbiguousError, ApiError, InputError, NotFoundError
from libre_devops_helpers.core.sorting import natural_key
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.detections.models import DetectionRule

_PATH = "/beta/security/rules/detectionRules"
AZURE_CLI_APP_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
SCOPE_HINT = (
    "custom detection rules need CustomDetection.Read.All on the Graph token. The Azure CLI "
    "cannot ask for it: use an interactive or device-code profile whose app has it, or have "
    f"an admin consent it for the Azure CLI's app ({AZURE_CLI_APP_ID})"
)


class DetectionsClient(GraphServiceClient):
    """Custom detection rules, read only. Close it (or use ``with``) when done."""

    API_NAME = "Defender XDR detections (Microsoft Graph)"

    def rules(self) -> list[DetectionRule]:
        """Every rule, by name (``web2`` before ``web10``, whatever the case)."""
        return sorted(
            (DetectionRule.from_json(item) for item in self.raw_rules()),
            key=lambda rule: natural_key(rule.display_name),
        )

    def raw_rules(self) -> list[dict[str, object]]:
        """Every rule as Graph returns it, following its pages, for export."""
        try:
            return list(self.api.get_all(_PATH))
        except ApiError as exc:
            raise _explained(exc) from None

    def rule(self, ref: str) -> DetectionRule:
        """One rule, by its id (a number) or its exact display name, whatever the case."""
        return DetectionRule.from_json(self.raw_rule(ref))

    def raw_rule(self, ref: str) -> dict[str, object]:
        """One rule as Graph returns it, by id or display name (see ``rule``)."""
        wanted = ref.strip()
        if not wanted:
            raise InputError("no rule named", hint="pass a rule's display name or its id")
        if wanted.isdigit():
            try:
                return self.api.get(f"{_PATH}/{quote(wanted, safe='')}")
            except ApiError as exc:
                if exc.status == 404:
                    raise NotFoundError(f"no custom detection rule has id {wanted}") from None
                raise _explained(exc) from None
        named = [item for item in self.raw_rules() if _named(item, wanted)]
        if not named:
            raise NotFoundError(
                f"no custom detection rule is named {wanted!r}",
                hint="list them with 'xdr detections list', or pass the rule's id",
            )
        if len(named) > 1:
            ids = ", ".join(str(item.get("id")) for item in named)
            raise AmbiguousError(
                f"{len(named)} rules are named {wanted!r}: {ids}", hint="pass the id instead"
            )
        return named[0]


def _named(item: dict[str, object], name: str) -> bool:
    return str(item.get("displayName") or "").casefold() == name.casefold()


def _explained(exc: ApiError) -> ApiError:
    # A suspended service answers 403 too, and its own hint says why better.
    if exc.status in {401, 403} and "suspended" not in str(exc).lower():
        return ApiError(
            str(exc), status=exc.status, code=exc.code, request_id=exc.request_id, hint=SCOPE_HINT
        )
    return exc
