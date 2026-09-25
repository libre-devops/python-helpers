"""Reading a Consumption Logic App workflow document, whatever shape it arrives in.

A definition arrives in one of three shapes, and the difference matters:

- ``code-view``: the designer's code view, ``{"definition": {...}, "parameters": {...}}``.
- ``arm``: an ARM resource GET, ``{"properties": {"definition": {...}, ...}, ...}``.
- ``bare``: a template's bare definition, ``{"$schema": ..., "triggers": ..., "actions": ...}``.

A wrapper's ``parameters`` block holds VALUES; a bare definition's top-level
``parameters`` holds its DECLARATIONS. Reading one as the other is the classic round-trip
trap, so the two are always kept apart here. A workflow definition has no top-level
``definition`` or ``properties`` key of its own, so telling the shapes apart is exact.

Templates for Terraform's ``templatefile`` (``.json.tftpl``) are not JSON while they hold
``${...}`` tokens; those are blanked first, so their shape can still be checked.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libre_devops_helpers.core import fields
from libre_devops_helpers.core.errors import InputError

TOKEN_MARK = "TFTPL_TOKEN"  # what an unrendered ${...} becomes, so the text parses
SHAPES = ("code-view", "arm", "bare")


@dataclass(frozen=True)
class WorkflowDocument:
    """A workflow document, unwrapped: its definition, and the values beside it."""

    source: str
    name: str | None
    shape: str
    definition: Mapping[str, Any]
    parameter_values: Mapping[str, Any] | None  # None for a bare definition, which has none
    text: str

    @property
    def declarations(self) -> Mapping[str, Any] | None:
        """The parameters the definition declares, or None when it declares none."""
        value = self.definition.get("parameters")
        return value if isinstance(value, Mapping) else None

    @property
    def triggers(self) -> Mapping[str, Any]:
        """The definition's triggers by name; empty when it has none."""
        return fields.mapping(self.definition.get("triggers"))

    @property
    def actions(self) -> Mapping[str, Any]:
        """The definition's actions by name; empty when it has none."""
        return fields.mapping(self.definition.get("actions"))


@dataclass(frozen=True)
class ActionNode:
    """One action, wherever it sits: ``path`` names it through its containers."""

    name: str
    path: str
    action: Mapping[str, Any]


def token_safe_json(text: str) -> str:
    """``text`` with each Terraform ``${...}`` token blanked, so it parses as JSON.

    Where a token sits decides the replacement, which is why this scans rather than using
    a regex: inside a JSON string it becomes bare text, but standing alone in value
    position (``"interval": ${x}``) it needs quotes of its own. Escapes and brace nesting
    are tracked, so a token holding braces is one unit. ``$${`` is templatefile's escaped
    literal (it renders as ``${``), so it is not a token. Logic App expressions use
    ``@{...}``, so a ``${...}`` is always a Terraform token here.
    """
    out: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            if char == "\\" and index + 1 < length:
                out.append(text[index : index + 2])  # an escape carries its next character
                index += 2
                continue
            if char == '"':
                in_string = False
                out.append(char)
                index += 1
                continue
        elif char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if text.startswith("$${", index):
            out.append("${")
            index += 3
            continue
        if text.startswith("${", index):
            end = _token_end(text, index + 1)
            if end is not None:
                out.append(TOKEN_MARK if in_string else f'"{TOKEN_MARK}"')
                index = end + 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _token_end(text: str, opening: int) -> int | None:
    """The index of the brace that closes the one at ``opening``, or None."""
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return position
    return None


def load(path: Path) -> WorkflowDocument:
    """Read and unwrap the document at ``path`` (``.json`` or ``.json.tftpl``)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError(f"Logic App definition file not found: {path}") from None
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from None
    return parse(text, str(path), default_name=workflow_name_from(path))


def parse(
    text: str, source: str = "<string>", *, default_name: str | None = None
) -> WorkflowDocument:
    """Unwrap a document already read, from ``source`` (a path, or ``<string>``)."""
    if not text.strip():
        raise InputError(f"Logic App definition {source} is empty")
    try:
        parsed = json.loads(token_safe_json(text))
    except ValueError as exc:
        raise InputError(f"Logic App definition {source} is not JSON: {exc}") from None
    if not isinstance(parsed, Mapping):
        raise InputError(f"Logic App definition {source} is not a JSON object")
    properties = parsed.get("properties")
    if isinstance(properties, Mapping) and isinstance(properties.get("definition"), Mapping):
        shape, definition, values = "arm", properties["definition"], properties.get("parameters")
    elif isinstance(parsed.get("definition"), Mapping):
        shape, definition, values = "code-view", parsed["definition"], parsed.get("parameters")
    else:
        shape, definition, values = "bare", parsed, None
    name = parsed.get("name") if isinstance(parsed.get("name"), str) else default_name
    return WorkflowDocument(
        source=source,
        name=name,
        shape=shape,
        definition=definition,
        parameter_values=values if isinstance(values, Mapping) else None,
        text=text,
    )


def workflow_name_from(path: Path) -> str:
    """``router`` for ``router.json`` or ``router.json.tftpl``."""
    name = path.name
    for suffix in (".tftpl", ".json"):
        name = name.removesuffix(suffix)
    return name


def action_nodes(actions: Mapping[str, Any] | None, prefix: str = "") -> Iterator[ActionNode]:
    """Every action, however deeply nested, each with its full path.

    The workflow language nests actions: a Scope, Foreach and Until carry ``actions``; an
    If adds ``else.actions``; a Switch carries ``cases.<name>.actions`` and
    ``default.actions``. Reading only the top level sees a fraction of the workflow.
    """
    if not isinstance(actions, Mapping):
        return
    for name, action in actions.items():
        if not isinstance(action, Mapping):
            continue
        path = f"{prefix}/{name}" if prefix else name
        yield ActionNode(name, path, action)
        containers: list[Any] = [action.get("actions")]
        for branch in ("else", "default"):
            node = action.get(branch)
            if isinstance(node, Mapping):
                containers.append(node.get("actions"))
        cases = action.get("cases")
        if isinstance(cases, Mapping):
            containers.extend(
                case.get("actions") for case in cases.values() if isinstance(case, Mapping)
            )
        for container in containers:
            yield from action_nodes(container, path)
