"""Consumption Logic Apps in Azure: read deployed workflows, and ask Azure to validate one.

Validating goes to the resource provider's validate endpoint, which type-checks a whole
definition and gives the provider's own verdict while creating and costing nothing. It
is the authority the offline checks defer to: whether a property is accepted on the API
version, whether an expression type-checks, whether a connector action is well formed.
It validates the definition, not the estate around it, so a missing dispatch target
(``NestedWorkflowNotFound``) is for ``deploy_order`` to prevent, not for this to catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError
from libre_devops_helpers.core.util import is_guid
from libre_devops_helpers.microsoft.api_clients import ArmServiceClient
from libre_devops_helpers.microsoft.logicapps.document import WorkflowDocument

API_VERSION = "2019-05-01"
_GROUP_API = "2021-04-01"
_NAME = re.compile(r"[A-Za-z0-9._()-]{1,90}")
_LOCATION = re.compile(r"[a-z0-9]{2,40}")


@dataclass(frozen=True)
class Validation:
    """The provider's verdict on a definition."""

    workflow: str
    location: str
    valid: bool
    code: str | None
    message: str


class LogicAppsClient(ArmServiceClient):
    """Reads Consumption Logic App workflows through ARM. Close it when done."""

    def workflows(self, subscription: str, resource_group: str) -> list[dict[str, Any]]:
        """Every Consumption workflow in the resource group, as ARM returns it."""
        path = f"{_group_path(subscription, resource_group)}/providers/Microsoft.Logic/workflows"
        return list(
            self.api.get_all(path, params={"api-version": API_VERSION}, next_link="nextLink")
        )

    def workflow(self, subscription: str, resource_group: str, name: str) -> dict[str, Any]:
        """One workflow, whole: its definition, parameter values and all."""
        group = _group_path(subscription, resource_group)
        path = f"{group}/providers/Microsoft.Logic/workflows/{_name(name)}"
        try:
            return self.api.get(path, params={"api-version": API_VERSION})
        except ApiError as exc:
            if exc.status == 404:
                raise NotFoundError(f"no workflow {name!r} in {resource_group}") from None
            raise

    def location_of(self, subscription: str, resource_group: str) -> str:
        """The resource group's region, where a workflow in it would live."""
        group = self.api.get(
            _group_path(subscription, resource_group), params={"api-version": _GROUP_API}
        )
        location = group.get("location")
        if not isinstance(location, str) or not location:
            raise ApiError(f"resource group {resource_group} has no location")
        return location

    def validate(
        self,
        document: WorkflowDocument,
        *,
        subscription: str,
        resource_group: str,
        location: str,
        name: str | None = None,
    ) -> Validation:
        """Ask the provider whether it would accept ``document``; nothing is deployed."""
        workflow = _name(name or document.name or "ldo-validate-probe")
        if not _LOCATION.fullmatch(location):
            raise InputError(f"{location!r} is not an Azure region name, such as uksouth")
        # The body is a workflow resource: the definition, and the parameter VALUES beside
        # it. A declaration with no value is exactly what the provider rejects.
        properties: dict[str, Any] = {"definition": dict(document.definition)}
        if document.parameter_values is not None:
            properties["parameters"] = dict(document.parameter_values)
        path = (
            f"{_group_path(subscription, resource_group)}/providers/Microsoft.Logic"
            f"/locations/{location}/workflows/{workflow}/validate"
        )
        try:
            self.api.request(
                "POST",
                path,
                params={"api-version": API_VERSION},
                json_body={"location": location, "properties": properties},
                allow_empty=True,
            )
        except ApiError as exc:
            if exc.status == 400:
                return Validation(workflow, location, False, exc.code, str(exc))
            raise
        return Validation(workflow, location, True, None, "accepted")


def _group_path(subscription: str, resource_group: str) -> str:
    if not is_guid(subscription):
        raise InputError(f"{subscription!r} is not a subscription id")
    if not re.fullmatch(r"[-\w._()]{1,90}", resource_group) or resource_group.endswith("."):
        raise InputError(f"{resource_group!r} is not a resource group name")
    return f"/subscriptions/{subscription}/resourceGroups/{quote(resource_group)}"


def _name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise InputError(f"{name!r} is not a Logic App workflow name")
    return name
