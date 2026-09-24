import json
from pathlib import Path

import pytest

from fakes.logicapps import ARM_RESOURCE, BARE, CODE_VIEW, write
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.logicapps import (
    TOKEN_MARK,
    action_nodes,
    load,
    parse,
    workflow_name_from,
)


def text(document) -> str:
    return json.dumps(document)


def bare_with(inputs: str) -> str:
    """The bare definition with its Compose inputs replaced by raw JSON text."""
    return text(BARE).replace('"inputs": "x"', inputs)


def test_the_code_view_keeps_values_apart_from_declarations():
    document = parse(text(CODE_VIEW))
    assert document.shape == "code-view"
    assert "ticket_prefix" in document.parameter_values
    assert "ticket_prefix" in document.declarations


def test_an_arm_resource_is_unwrapped_from_properties():
    document = parse(text(ARM_RESOURCE))
    assert (document.shape, document.name) == ("arm", "logic-arm")
    assert document.parameter_values == {"ticket_prefix": {"value": "SIR"}}
    assert document.actions["Compose"]["inputs"] == "x"


def test_a_bare_definition_has_declarations_but_no_values():
    document = parse(text(BARE))
    assert document.shape == "bare"
    assert document.parameter_values is None
    assert "ticket_prefix" in document.declarations


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ('"inputs": "${audit_table_name}"', TOKEN_MARK),  # a token inside a string
        ('"inputs": ${recurrence_interval}', TOKEN_MARK),  # unquoted, in value position
        ('"inputs": "prefix ${table_name} suffix"', f"prefix {TOKEN_MARK} suffix"),
        ('"inputs": "$${not_a_token}"', "${not_a_token}"),  # templatefile's escaped literal
        ('"inputs": ${jsonencode({ a = 1 })}', TOKEN_MARK),  # braces inside, one token
        (
            '"inputs": "@{triggerBody()?[\'id\']}"',
            "@{triggerBody()?['id']}",
        ),  # a Logic App expression
        ('"inputs": "a \\"${quoted}\\" b"', f'a "{TOKEN_MARK}" b'),  # escaped quotes
    ],
)
def test_terraform_template_tokens_are_blanked_where_they_sit(inputs, expected):
    assert parse(bare_with(inputs)).actions["Compose"]["inputs"] == expected


def test_content_that_is_not_json_or_empty_or_missing_is_refused(tmp_path):
    with pytest.raises(InputError, match="is not JSON"):
        parse("not json at all")
    with pytest.raises(InputError, match="is empty"):
        parse("   ")
    with pytest.raises(InputError, match="not a JSON object"):
        parse("[1, 2]")
    with pytest.raises(InputError, match="not found"):
        load(tmp_path / "missing.json")


def test_files_are_named_after_their_stem(tmp_path):
    assert workflow_name_from(Path("router.json.tftpl")) == "router"
    assert workflow_name_from(Path("router.json")) == "router"
    template = write(tmp_path, "handler.json.tftpl", BARE)
    renamed = write(tmp_path, "renamed.json", ARM_RESOURCE)
    assert load(template).name == "handler"
    assert load(renamed).name == "logic-arm"  # its own name wins


def test_every_nested_action_is_walked_with_its_path():
    actions = {
        "Scope": {"type": "Scope", "actions": {"Inner": {"type": "Compose"}}},
        "If": {
            "type": "If",
            "actions": {"Yes": {"type": "Compose"}},
            "else": {"actions": {"No": {"type": "Compose"}}},
        },
        "Switch": {
            "type": "Switch",
            "cases": {"mde": {"actions": {"Case": {"type": "Compose"}}}},
            "default": {"actions": {"Fallback": {"type": "Compose"}}},
        },
        "Broken": "not an action",
    }
    assert [node.path for node in action_nodes(actions)] == [
        "Scope",
        "Scope/Inner",
        "If",
        "If/Yes",
        "If/No",
        "Switch",
        "Switch/Fallback",  # default, then the cases, as the PowerShell walks them
        "Switch/Case",
    ]
