"""Logic App workflow documents in each shape Azure produces, for the Logic App tests.

Each is minimal but real, taken from the LibreDevOpsHelpers LogicApps suite, so the
tests follow the paths a portal export does.
"""

import json
from pathlib import Path

SENTINEL_KEY = "@parameters('$connections')['azuresentinel']['connectionId']"
SERVICENOW_KEY = "@parameters('$connections')['servicenow']['connectionId']"
SCHEMA = (
    "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/"
    "2016-06-01/workflowdefinition.json#"
)
ZERO = "/subscriptions/00000000-0000-0000-0000-000000000000"
MANAGED_API = f"{ZERO}/providers/Microsoft.Web/locations/uksouth/managedApis"
CONNECTIONS = f"{ZERO}/resourceGroups/rg-int/providers/Microsoft.Web/connections"

# The designer's code view: the definition, and the resolved VALUES beside it.
CODE_VIEW = {
    "definition": {
        "$schema": SCHEMA,
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"type": "Object", "defaultValue": {}},
            "ticket_prefix": {"type": "String"},
            "retry_count": {"type": "Int"},
            "category_map": {"type": "Array"},
        },
        "triggers": {"manual": {"type": "Request", "kind": "Http"}},
        "actions": {"Compose": {"type": "Compose", "inputs": "@parameters('ticket_prefix')"}},
    },
    "parameters": {
        "ticket_prefix": {"value": "SIR"},
        "retry_count": {"value": 3},
        "category_map": {"value": [{"contains": "DDoS", "value": "Denial of Service"}]},
        "$connections": {
            "type": "Object",
            "value": {
                "servicenow": {
                    "id": f"{MANAGED_API}/service-now",
                    "connectionId": f"{CONNECTIONS}/api-servicenow",
                    "connectionName": "api-servicenow",
                    "connectionProperties": {"authentication": {"type": "ManagedServiceIdentity"}},
                },
                "azuresentinel": {
                    "id": f"{MANAGED_API}/azuresentinel",
                    "connectionId": f"{CONNECTIONS}/api-sentinel",
                    "connectionName": "api-sentinel",
                    "connectionProperties": {},
                },
            },
        },
    },
}

# An ARM resource GET: the definition lives under properties.
ARM_RESOURCE = {
    "id": f"{ZERO}/resourceGroups/rg/providers/Microsoft.Logic/workflows/logic-arm",
    "name": "logic-arm",
    "type": "Microsoft.Logic/workflows",
    "location": "uksouth",
    "properties": {
        "definition": {
            "$schema": SCHEMA,
            "parameters": {"ticket_prefix": {"type": "String"}},
            "triggers": {"manual": {"type": "Request", "kind": "Http"}},
            "actions": {"Compose": {"type": "Compose", "inputs": "x"}},
        },
        "parameters": {"ticket_prefix": {"value": "SIR"}},
    },
}

# A bare definition: its top-level "parameters" is DECLARATIONS, never values.
BARE = {
    "$schema": SCHEMA,
    "parameters": {"ticket_prefix": {"type": "String"}},
    "triggers": {"manual": {"type": "Request", "kind": "Http"}},
    "actions": {"Compose": {"type": "Compose", "inputs": "x"}},
}

SECURE_CODE_VIEW = {
    "definition": {
        "parameters": {"api_secret": {"type": "SecureString"}},
        "triggers": {"manual": {"type": "Request", "kind": "Http"}},
        "actions": {"Compose": {"type": "Compose", "inputs": "x"}},
    },
    "parameters": {"api_secret": {"value": "hunter2"}},
}

# Connections referenced from a trigger and a nested action, both wired.
REFERENCES = {
    "definition": {
        "triggers": {
            "Incident": {
                "type": "ApiConnection",
                "inputs": {"host": {"connection": {"name": SENTINEL_KEY}}},
            }
        },
        "actions": {
            "Outer": {
                "type": "Scope",
                "actions": {
                    "Find": {
                        "type": "ApiConnection",
                        "inputs": {"host": {"connection": {"name": SERVICENOW_KEY}}},
                    }
                },
            }
        },
        "parameters": {"$connections": {"type": "Object", "defaultValue": {}}},
    },
    "parameters": {
        "$connections": {
            "value": {"azuresentinel": {"connectionId": "/a"}, "servicenow": {"connectionId": "/b"}}
        }
    },
}


def dispatcher(target: str | None) -> dict:
    """A code view workflow whose one action dispatches to ``target`` (or does nothing)."""
    actions = {}
    if target:
        workflow_id = (
            f"/subscriptions/x/resourceGroups/y/providers/Microsoft.Logic/workflows/{target}"
        )
        actions["Call"] = {
            "type": "Workflow",
            "inputs": {"host": {"workflow": {"id": workflow_id}}},
        }
    return {"definition": {"triggers": {}, "actions": actions}, "parameters": {}}


def write(folder: Path, name: str, document: dict | str) -> Path:
    path = folder / name
    path.write_text(document if isinstance(document, str) else json.dumps(document), "utf-8")
    return path
