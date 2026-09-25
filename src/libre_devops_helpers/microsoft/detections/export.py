"""Custom detection rules as YAML files for ``terraform-msgraph-xdr-custom-detection-rules``.

The brownfield half of detections as code: a rule made by hand in the portal becomes one
YAML file in the Terraform module's analyst layout, ready to review, commit and import.
It is the conversion LibreDevOpsHelpers' ``Export-LdoCustomDetectionRule`` does:

- Graph's camelCase becomes the module's snake_case authoring schema.
- Each file goes under ``<category>/<rule-name>.yaml``, the category being the rule's
  first ATT&CK tactic in kebab case (``command-and-control``), else ``uncategorised``.
- The rule's server id is kept, since the module keys rules by it, so ``terraform
  import`` addresses and later plans line up. ``keep_id=False`` leaves it out, for a
  backup meant to create the rules anew, in this tenant or another.
- A rule written the old way (a schedule ``period``, ``category`` and ``mitreTechniques``,
  ``impactedAssets``, ``responseActions``) is converted where it can be, and what cannot be
  becomes a ``TODO(export)`` comment in the file, never dropped quietly.

Two things the module's schema would refuse are noted as well: a rule Defender turned off
itself (``autoDisabled``) is written ``disabled``, since the schema allows only enabled and
disabled, and a rule with no entity mappings, which the schema requires.

What a tenant's rule holds reaches the file only as YAML values, quoted where they need
to be, or in a comment flattened to one line, so a rule's name or text cannot add keys.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from libre_devops_helpers.core import brand, fields, yaml_text
from libre_devops_helpers.microsoft.detections.models import (
    DetectionRule,
    alert_template,
    rule_frequency,
    rule_status,
)

SCHEMA_URL = (
    "https://raw.githubusercontent.com/libre-devops/terraform-msgraph-xdr-custom-detection-rules"
    "/main/schema/custom-detection.schema.json"
)
# The 14 enterprise ATT&CK tactics, as the module (and Graph) spell them.
TACTICS = (
    "Reconnaissance",
    "ResourceDevelopment",
    "InitialAccess",
    "Execution",
    "Persistence",
    "PrivilegeEscalation",
    "DefenseEvasion",
    "CredentialAccess",
    "Discovery",
    "LateralMovement",
    "Collection",
    "CommandAndControl",
    "Exfiltration",
    "Impact",
)
# The one family of Graph names whose snake case is not the camelCase split: oAuth, which
# the module writes as oauth. Every other group, action and column name is split.
_NAMES = {
    "oAuthApplications": "oauth_applications",
    "oAuthAppIdColumn": "oauth_app_id_column",
}
_CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")


@dataclass(frozen=True)
class ExportedRule:
    """One rule as a file: where it goes under the export folder, what it holds, and what
    the person should review before committing it."""

    rule: DetectionRule
    path: PurePosixPath
    text: str
    notes: tuple[str, ...]


def export_rules(
    rules: Iterable[Mapping[str, Any]],
    *,
    keep_id: bool = True,
    now: datetime | None = None,
    exporter: str = brand.DISPLAY_NAME,
) -> list[ExportedRule]:
    """Each rule as a file of its own. A rule whose name makes the same file name as one
    before it gets its id added (``rule-name-1234.yaml``), so neither is lost."""
    exported: list[ExportedRule] = []
    taken: set[PurePosixPath] = set()
    for data in rules:
        found = export_rule(data, keep_id=keep_id, now=now, exporter=exporter)
        if found.path in taken:
            path = found.path.with_name(f"{found.path.stem}-{_safe(found.rule.id)}.yaml")
            found = ExportedRule(found.rule, path, found.text, found.notes)
        taken.add(found.path)
        exported.append(found)
    return exported


def export_rule(
    data: Mapping[str, Any],
    *,
    keep_id: bool = True,
    now: datetime | None = None,
    exporter: str = brand.DISPLAY_NAME,
) -> ExportedRule:
    """One rule (as Graph returns it) as the module's YAML, with a header saying where it
    came from and what to review."""
    spec, notes = rule_spec(data, keep_id=keep_id)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    header = [
        f"# yaml-language-server: $schema={SCHEMA_URL}",
        "#",
        f"# Exported from Microsoft Defender XDR by {exporter} on {when:%Y-%m-%d %H:%M}Z.",
    ]
    if keep_id:
        header += [
            "# The id is the server assigned rule id, kept on purpose: the Terraform module keys",
            "# rules by id, so terraform import addresses and later plans line up. New rules",
            "# authored by hand should omit id. Review this file before committing.",
        ]
    header += [f"# TODO(export): {_one_line(note)}" for note in notes]
    text = "\n".join(header) + "\n" + yaml_text.dumps(spec)
    rule = DetectionRule.from_json(data)
    return ExportedRule(rule, _path(rule, spec), text, tuple(notes))


def rule_spec(data: Mapping[str, Any], *, keep_id: bool = True) -> tuple[dict[str, Any], list[str]]:
    """The rule in the module's authoring schema, and the notes for what needs review."""
    notes: list[str] = []
    spec: dict[str, Any] = {}
    if keep_id and fields.text(data, "id"):
        spec["id"] = fields.text(data, "id")
    spec["display_name"] = fields.text(data, "displayName")
    if fields.text(data, "description"):
        spec["description"] = fields.text(data, "description")
    spec["status"] = _status(data, notes)
    spec["frequency"] = _frequency(data, notes)
    spec["query"] = fields.text(fields.mapping(data.get("queryCondition")), "queryText")
    spec["alert"] = _alert(alert_template(data), notes)
    action = fields.mapping(data.get("detectionAction"))
    groups = _device_groups(action)
    if groups:
        spec["device_groups"] = groups
    actions = _automated_actions(action, notes)
    if actions:
        spec["automated_actions"] = actions
    return spec, notes


def _status(data: Mapping[str, Any], notes: list[str]) -> str:
    status = rule_status(data) or "enabled"
    if status.casefold() == "autodisabled":
        notes.append(
            "Defender turned this rule off itself (autoDisabled), usually after its query "
            "failed again and again; it is exported as disabled: fix the query before enabling it."
        )
        return "disabled"
    return status


def _frequency(data: Mapping[str, Any], notes: list[str]) -> str:
    frequency = rule_frequency(data)
    if frequency:
        return frequency
    period = fields.text(fields.mapping(data.get("schedule")), "period")
    notes.append(f"legacy schedule period {period!r} has no mapping; defaulted to PT24H, review.")
    return "PT24H"


def _alert(template: Mapping[str, Any], notes: list[str]) -> dict[str, Any]:
    alert: dict[str, Any] = {}
    for key, name in (("title", "title"), ("description", "description")):
        if fields.text(template, key):
            alert[name] = fields.text(template, key)
    alert["severity"] = fields.text(template, "severity")
    if fields.text(template, "recommendedActions"):
        alert["recommended_actions"] = fields.text(template, "recommendedActions")
    mitre = _mitre(template, notes)
    if mitre:
        alert["mitre"] = mitre
    details = _plain(fields.mapping(template.get("customDetails")))
    if details:
        alert["custom_details"] = details
    mappings = _entity_mappings(template, notes)
    if mappings:
        alert["entity_mappings"] = mappings
    return alert


def _mitre(template: Mapping[str, Any], notes: list[str]) -> list[dict[str, Any]]:
    """The tactics, each with its techniques (a sub-technique keeps its parent)."""
    entries = []
    for item in fields.items(template.get("tactics")):
        tactic = fields.mapping(item)
        entry: dict[str, Any] = {"tactic": fields.text(tactic, "tactic")}
        techniques = [_technique(fields.mapping(t)) for t in fields.items(tactic.get("techniques"))]
        if techniques:
            entry["techniques"] = techniques
        entries.append(entry)
    if entries or not fields.text(template, "category"):
        return entries
    # The legacy shape: one category, which may be a tactic, and a flat list of techniques.
    category = fields.text(template, "category")
    legacy = [str(item) for item in fields.items(template.get("mitreTechniques"))]
    if category in TACTICS:
        return [{"tactic": category, **({"techniques": legacy} if legacy else {})}]
    notes.append(
        f"legacy category {category!r} is not an ATT&CK tactic; techniques not carried: "
        f"{', '.join(legacy) or 'none'}."
    )
    return []


def _technique(technique: Mapping[str, Any]) -> str | dict[str, Any]:
    subs = [str(sub) for sub in fields.items(technique.get("subTechniques"))]
    name = fields.text(technique, "technique")
    return {"technique": name, "sub_techniques": subs} if subs else name


def _entity_mappings(template: Mapping[str, Any], notes: list[str]) -> dict[str, Any]:
    mappings = _groups(fields.mapping(template.get("entityMappings")))
    if mappings:
        return mappings
    assets = fields.items(template.get("impactedAssets"))
    if assets:
        kinds = ", ".join(fields.text(fields.mapping(asset), "@odata.type") for asset in assets)
        notes.append(
            "legacy impactedAssets not converted (the module uses entity_mappings); "
            f"review: {kinds}."
        )
    else:
        notes.append("the rule maps no entities; the module needs at least one in entity_mappings.")
    return {}


def _device_groups(action: Mapping[str, Any]) -> list[str]:
    scope = fields.mapping(action.get("organizationalScope"))
    groups = fields.items(scope.get("deviceGroups")) or fields.items(scope.get("scopeNames"))
    return [str(group) for group in groups if group]


def _automated_actions(action: Mapping[str, Any], notes: list[str]) -> dict[str, Any]:
    actions = _groups(fields.mapping(action.get("automatedActions")))
    if actions:
        notes.append(
            "the rule carries automated_actions: the module call needs "
            "allow_automated_actions = true."
        )
    elif fields.items(action.get("responseActions")):
        notes.append(
            "legacy responseActions not converted (the module uses automated_actions); "
            "review the original rule."
        )
    return actions


def _groups(source: Mapping[str, Any]) -> dict[str, Any]:
    """Entity mapping groups, or automated actions: each group snake cased, with its items'
    keys snake cased too, and the empty ones left out."""
    found = {}
    for name, entries in source.items():
        if name.startswith("@"):
            continue
        items = [_snake_keys(fields.mapping(entry)) for entry in fields.items(entries)]
        items = [item for item in items if item]
        if items:
            found[_snake(name)] = items
    return found


def _snake_keys(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        _snake(key): value
        for key, value in item.items()
        if not key.startswith("@") and value is not None and value != ""
    }


def _plain(source: Mapping[str, Any]) -> dict[str, Any]:
    """``source`` without Graph's ``@odata`` annotations."""
    return {key: value for key, value in source.items() if not key.startswith("@")}


def _snake(name: str) -> str:
    return _NAMES.get(name) or _CAMEL.sub(r"_\1", name).lower()


def _path(rule: DetectionRule, spec: Mapping[str, Any]) -> PurePosixPath:
    """``<category>/<slug>.yaml``: the first tactic in kebab case, and the rule's name, each
    reduced to letters, digits and hyphens, so no name can reach outside the folder."""
    mitre = spec["alert"].get("mitre") or []
    tactic = mitre[0]["tactic"] if mitre else ""
    category = _slug(_CAMEL.sub(r"-\1", tactic)) or "uncategorised"
    name = _slug(rule.display_name) or f"rule-{_safe(rule.id) or 'unnamed'}"
    return PurePosixPath(category, f"{name}.yaml")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text)


def _one_line(text: str) -> str:
    """A note for a comment: one line, whatever the rule's own text held."""
    return " ".join(text.split())


@dataclass(frozen=True)
class Written:
    """What became of one exported rule on disk: ``written``, ``kept`` (a file was there
    already, and nothing forced it) or ``refused`` (a link in the way)."""

    exported: ExportedRule
    target: Path
    result: str


def write_rules(
    exported: Iterable[ExportedRule], folder: Path, *, force: bool = False
) -> list[Written]:
    """Write each rule under ``folder`` at its ``path``, creating folders as needed.

    A file already there is kept unless ``force``. A symbolic link in the way is never
    written through, and nothing is written outside ``folder`` (each path is made of
    letters, digits and hyphens anyway, so this is a second guard, not the first).
    """
    root = folder.resolve()
    results = []
    for item in exported:
        target = folder / item.path
        results.append(Written(item, target, _write_one(item, target, root, force)))
    return results


def _write_one(item: ExportedRule, target: Path, root: Path, force: bool) -> str:
    if target.is_symlink() or not target.parent.resolve().is_relative_to(root):
        return "refused"
    if target.exists() and not force:
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(root):
        return "refused"  # a linked folder, made or met on the way
    target.write_text(item.text, encoding="utf-8", newline="\n")
    return "written"
