"""Consumption Logic App workflows: offline checks, Azure's own validation, export.

Ported from the LibreDevOpsHelpers LogicApps module. The offline half checks a
definition against the contract Azure enforces, with no network; the online half reads
deployed workflows and asks the resource provider to validate a definition without
deploying it.

Public API::

    from libre_devops_helpers.microsoft.logicapps import check, load

    findings = check(load(Path("router.json")), connections=["office365"])
"""

from libre_devops_helpers.microsoft.logicapps.checks import (
    Connection,
    ConnectionReference,
    DeployStep,
    Difference,
    Finding,
    ParameterStatus,
    check,
    compare,
    connection_references,
    connections_of,
    deploy_order,
    parameter_status,
    rewrite_references,
    with_parameter_defaults,
)
from libre_devops_helpers.microsoft.logicapps.client import (
    API_VERSION,
    LogicAppsClient,
    Validation,
)
from libre_devops_helpers.microsoft.logicapps.document import (
    SHAPES,
    TOKEN_MARK,
    ActionNode,
    WorkflowDocument,
    action_nodes,
    load,
    parse,
    token_safe_json,
    workflow_name_from,
)
from libre_devops_helpers.microsoft.resources import Requirement

# ARM access rests on Azure RBAC (Logic App Reader, or Reader), not token scopes.
REQUIREMENTS: tuple[Requirement, ...] = ()

__all__ = [
    "API_VERSION",
    "REQUIREMENTS",
    "SHAPES",
    "TOKEN_MARK",
    "ActionNode",
    "Connection",
    "ConnectionReference",
    "DeployStep",
    "Difference",
    "Finding",
    "LogicAppsClient",
    "ParameterStatus",
    "Validation",
    "WorkflowDocument",
    "action_nodes",
    "check",
    "compare",
    "connection_references",
    "connections_of",
    "deploy_order",
    "load",
    "parameter_status",
    "parse",
    "rewrite_references",
    "token_safe_json",
    "with_parameter_defaults",
    "workflow_name_from",
]
