"""Custom detection rules as Graph returns them, and the schema their exports must meet.

``schemas/custom-detection.schema.json`` is a copy of the authoring schema of
libre-devops/terraform-msgraph-xdr-custom-detection-rules (schema/custom-detection.schema.json
at commit a30ba15c61f0). An exported file that meets it is one the module's plan accepts.
Refresh the copy when the module's schema changes.
"""

import json
from pathlib import Path

SCHEMA = json.loads(
    (Path(__file__).parent / "schemas" / "custom-detection.schema.json").read_text("utf-8")
)
PATH = "/beta/security/rules/detectionRules"


def rule(rule_id: str = "7506", name: str = "Certutil used to download remote content", **extra):
    """A rule in the current shape: status, schedule, queryCondition, detectionAction."""
    record = {
        "id": rule_id,
        "displayName": name,
        "description": "certutil fetching from the internet",
        "status": "enabled",
        "createdBy": "ana@example.com",
        "createdDateTime": "2026-07-01T09:00:00Z",
        "lastModifiedBy": "ana@example.com",
        "lastModifiedDateTime": "2026-09-20T09:00:00Z",
        "schedule": {"frequency": "PT3H", "nextRunDateTime": "2026-09-25T12:00:00Z"},
        "queryCondition": {
            "queryText": 'DeviceProcessEvents\n| where FileName =~ "certutil.exe"\n'
            "| project Timestamp, ReportId, DeviceId, DeviceName"
        },
        "detectionAction": {
            "alertTemplate": {
                "title": "Certutil download",
                "description": "certutil fetched remote content",
                "severity": "medium",
                "recommendedActions": "Recover and detonate the downloaded content.",
                "tactics": [
                    {
                        "tactic": "CommandAndControl",
                        "techniques": [
                            {"technique": "T1105"},
                            {"technique": "T1059", "subTechniques": ["T1059.001"]},
                        ],
                    }
                ],
                "customDetails": {"CommandLine": "ProcessCommandLine"},
                "entityMappings": {
                    "hosts": [{"deviceIdColumn": "DeviceId", "nameColumn": "DeviceName"}],
                },
            },
            "organizationalScope": {"deviceGroups": ["Workstations-Corp"]},
        },
    }
    record.update(extra)
    return record


def legacy_rule(rule_id: str = "42", name: str = "Old style rule"):
    """A rule written before 2026-10-01's clean-up: isEnabled, a schedule period, a category
    and mitreTechniques, impactedAssets and responseActions, and no status."""
    return {
        "id": rule_id,
        "displayName": name,
        "isEnabled": False,
        "schedule": {"period": "12H"},
        "queryCondition": {"queryText": "DeviceEvents | take 1"},
        "detectionAction": {
            "alertTemplate": {
                "title": "Old style",
                "severity": "low",
                "category": "Execution",
                "mitreTechniques": ["T1059"],
                "impactedAssets": [
                    {"@odata.type": "#microsoft.graph.security.impactedDeviceAsset"}
                ],
            },
            "responseActions": [
                {"@odata.type": "#microsoft.graph.security.isolateDeviceResponseAction"}
            ],
        },
    }
