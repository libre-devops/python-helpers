"""The shape of every command's ``-o json``: a contract with the scripts that read it.

Each command runs against a tenant that answers everything (``fakes.everything``), and
the shape of what it writes (every key, and the kind of value under it) is compared with
the one recorded in ``json_output.json``. A key renamed, dropped or turned from a list
into a string fails here, before it breaks someone's script.

A change that is meant goes in the changelog, then into the record:

    LDO_RECORD_JSON_OUTPUT=1 just test tests/project/test_json_output.py
"""

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from fakes.everything import CONFIG, Everything, invoke
from fakes.ids import SUBSCRIPTION
from fakes.logicapps import CODE_VIEW, REFERENCES, dispatcher, write
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.core import probe as reach
from libre_devops_helpers.core.network import Route
from libre_devops_helpers.core.probe import Probe

RECORD = Path(__file__).with_name("json_output.json")
RECORDING = os.environ.get("LDO_RECORD_JSON_OUTPUT") == "1"
TOKEN = make_jwt(graph_claims())

# Each command, with the arguments that make it write every part of its output.
COMMANDS: dict[str, list[str]] = {
    "az whoami": ["az", "whoami"],
    "azure automation accounts": ["azure", "automation", "accounts"],
    "azure automation jobs": ["azure", "automation", "jobs", "aa-ops"],
    "azure automation logs": ["azure", "automation", "logs", "aa-ops", "job-3"],
    "azure defender-plans": ["azure", "defender-plans"],
    "azure rbac": ["azure", "rbac", "ana@example.com"],
    "azure recommendations": ["azure", "recommendations"],
    "azure resource-graph": ["azure", "resource-graph", "resources | take 1"],
    "azure secure-score": ["azure", "secure-score", "--controls"],
    "azure subscriptions": ["azure", "subscriptions"],
    "devices av-signature": ["devices", "av-signature", "web01"],
    "devices check": ["devices", "check", "web01", "--intune", "--group", "Linux servers"],
    "devices show": ["devices", "show", "web01", "--intune"],
    "devices watch": ["devices", "watch", "web01", "--max-passes", "1"],
    "entra app-credentials": ["entra", "app-credentials"],
    "entra ca-policies": ["entra", "ca-policies"],
    "entra device-groups": ["entra", "device-groups", "web01"],
    "entra devices": ["entra", "devices", "web01", "--group", "Linux servers"],
    "entra group-devices": ["entra", "group-devices", "Linux servers"],
    "entra group-members": ["entra", "group-members", "Linux servers"],
    "entra inspect-token": ["entra", "inspect-token", "-"],
    "entra sign-ins": ["entra", "sign-ins"],
    "entra token": ["entra", "token", "graph"],
    "entra user-groups": ["entra", "user-groups", "ana@example.com"],
    "entra user-roles": ["entra", "user-roles", "ana@example.com"],
    "graph get": ["graph", "get", "me"],
    "graph get-app": ["graph", "get-app", "billing-api"],
    "graph get-device": ["graph", "get-device", "web01"],
    "graph get-group": ["graph", "get-group", "Linux servers"],
    "graph get-sp": ["graph", "get-sp", "billing-api"],
    "graph get-user": ["graph", "get-user", "ana@example.com"],
    "graph hunt": ["graph", "hunt", "DeviceInfo | take 1"],
    "graph token": ["graph", "token"],
    "graph whoami": ["graph", "whoami"],
    "intune devices": ["intune", "devices", "web01"],
    "keyvault expiry": ["keyvault", "expiry", "kv-app"],
    "logicapp check": ["logicapp", "check", "{workflow}"],
    "logicapp connections": ["logicapp", "connections", "{references}"],
    "logicapp diff": ["logicapp", "diff", "{workflow}", "{changed}"],
    "logicapp export": ["logicapp", "export", "--resource-group", "rg-apps", "--out", "{out}"],
    "logicapp order": ["logicapp", "order", "{workflows}"],
    "logicapp params": ["logicapp", "params", "{workflow}"],
    "logicapp references": ["logicapp", "references", "{references}"],
    "logicapp validate": ["logicapp", "validate", "{workflow}", "--resource-group", "rg-apps"],
    "logs ingestion": ["logs", "ingestion"],
    "logs query": ["logs", "query", "Heartbeat | take 1"],
    "network test": ["network", "test"],
    "pim active": ["pim", "active"],
    "pim approvals": ["pim", "approvals"],
    "pim eligible": ["pim", "eligible"],
    "pim requests": ["pim", "requests"],
    "pim settings": ["pim", "settings", "Owner", "--scope", "/subscriptions/{subscription}"],
    "profiles": ["profiles"],
    "snow apps": ["snow", "apps"],
    "snow instance": ["snow", "instance"],
    "snow token": ["snow", "token"],
    "snow whoami": ["snow", "whoami"],
    "xdr alerts": ["xdr", "alerts"],
    "xdr detections export": ["xdr", "detections", "export", "{out}"],
    "xdr detections list": ["xdr", "detections", "list"],
    "xdr detections show": ["xdr", "detections", "show", "7506"],
    "xdr hunt": ["xdr", "hunt", "DeviceInfo | take 1"],
    "xdr incidents latest": ["xdr", "incidents", "latest"],
    "xdr incidents list": ["xdr", "incidents", "list"],
    "xdr incidents show": ["xdr", "incidents", "show", "1"],
    "xdr incidents summary": ["xdr", "incidents", "summary"],
    "xdr incidents top": ["xdr", "incidents", "top"],
    "xdr indicators": ["xdr", "indicators"],
    "xdr machines": ["xdr", "machines", "web01"],
    "xdr stale": ["xdr", "stale"],
    "xdr timeline": ["xdr", "timeline", "web01"],
    "xdr vulns": ["xdr", "vulns", "web01"],
}
STDIN = {"entra inspect-token": TOKEN}


def shape(value: Any) -> Any:
    """What a script sees of ``value``: its keys, and the kind of each value, not the values.

    A list's shape is that of its items together, so a key that only some have still
    counts; an empty list is ``[]``.
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_merge([shape(item) for item in value])] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "string"


def _merge(shapes: list[Any]) -> Any:
    """One shape for values found in the same place: objects' keys together, lists' items
    together (an empty list fits any), and otherwise each kind seen, such as ``null |
    string``."""
    if all(isinstance(item, dict) for item in shapes):
        merged: dict[str, Any] = {}
        for item in shapes:
            for key, value in item.items():
                merged[key] = _merge([merged[key], value]) if key in merged else value
        return dict(sorted(merged.items()))
    if all(isinstance(item, list) for item in shapes):
        items = [item[0] for item in shapes if item]
        return [_merge(items)] if items else []
    kinds = sorted({json.dumps(item, sort_keys=True) for item in shapes})
    return json.loads(kinds[0]) if len(kinds) == 1 else " | ".join(kinds)


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def offline_network(monkeypatch):
    """``network test`` probes the real internet; here each probe is a pass, direct."""

    def probe(url, *, expect=range(200, 300), timeout=10.0, **_):
        return Probe(url, Route(None, "none"), True, 200, "HTTP 200", None, 0.1)

    monkeypatch.setattr(reach, "probe", probe)


def _workflow_files(folder: Path) -> dict[str, object]:
    """Logic App definitions for the offline commands: one, a changed copy, one wired to
    connections, and a folder of three that call each other."""
    changed = copy.deepcopy(CODE_VIEW)
    changed["definition"]["actions"]["Compose"]["inputs"] = "other"
    tiers = folder / "tiers"
    tiers.mkdir()
    for name, target in (("router", "dispatcher"), ("dispatcher", "handler"), ("handler", None)):
        write(tiers, f"{name}.json", dispatcher(target))
    return {
        "workflow": write(folder, "orders.json", CODE_VIEW),
        "changed": write(folder, "changed.json", changed),
        "references": write(folder, "wired.json", REFERENCES),
        "workflows": tiers,
        "out": folder / "exported",
        "subscription": SUBSCRIPTION,
    }


@pytest.mark.parametrize("name", list(COMMANDS))
def test_json_output_keeps_its_shape(name, config_file, tmp_path, offline_network):
    files = _workflow_files(tmp_path)
    args = [part.format(**files) for part in COMMANDS[name]]
    result = invoke(config_file, Everything(), [*args, "-o", "json"], stdin=STDIN.get(name))
    assert result.exit_code in (0, 3), result.output + repr(result.exception)
    found = shape(json.loads(result.stdout))
    recorded = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    if RECORDING:
        recorded[name] = found
        RECORD.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", "utf-8")
        return
    assert name in recorded, f"no recorded shape for {name!r}: record it (see the docstring)"
    assert found == recorded[name]


def test_every_command_that_writes_json_is_covered():
    from typer.main import get_command

    from libre_devops_helpers.cli.app import app

    def commands(group, prefix=()):
        for name, command in group.commands.items():
            if hasattr(command, "commands"):
                yield from commands(command, (*prefix, name))
            elif not command.hidden and any(
                "--output" in getattr(param, "opts", []) for param in command.params
            ):
                yield " ".join((*prefix, name))

    everything = {name for name in commands(get_command(app)) if not name.startswith("device ")}
    assert sorted(everything - set(COMMANDS)) == []


def test_nothing_is_recorded_for_a_command_that_is_gone():
    recorded = json.loads(RECORD.read_text(encoding="utf-8"))
    assert sorted(set(recorded) - set(COMMANDS)) == []
