"""Defender XDR custom detection rules: list them, read one, and export them as YAML.

Depends only on ``core`` and the shared Microsoft layer. Public API::

    from libre_devops_helpers.microsoft.detections import DetectionsClient, export_rules

    with DetectionsClient.create(tokens, tenant_id) as detections:
        off = [rule for rule in detections.rules() if rule.auto_disabled]
        for exported in export_rules(detections.raw_rules()):
            print(exported.path, exported.notes)
"""

from libre_devops_helpers.microsoft.detections.client import SCOPE_HINT, DetectionsClient
from libre_devops_helpers.microsoft.detections.export import (
    SCHEMA_URL,
    ExportedRule,
    Written,
    export_rule,
    export_rules,
    rule_spec,
    write_rules,
)
from libre_devops_helpers.microsoft.detections.models import (
    FREQUENCIES,
    STATUSES,
    DetectionRule,
)
from libre_devops_helpers.microsoft.detections.permissions import REQUIREMENTS

__all__ = [
    "FREQUENCIES",
    "REQUIREMENTS",
    "SCHEMA_URL",
    "SCOPE_HINT",
    "STATUSES",
    "DetectionRule",
    "DetectionsClient",
    "ExportedRule",
    "Written",
    "export_rule",
    "export_rules",
    "rule_spec",
    "write_rules",
]
