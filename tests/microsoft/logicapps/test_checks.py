import copy
import json

import pytest

from fakes.logicapps import ARM_RESOURCE, BARE, CODE_VIEW, REFERENCES, SECURE_CODE_VIEW, dispatcher
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.logicapps import (
    check,
    compare,
    connection_references,
    connections_of,
    deploy_order,
    parameter_status,
    parse,
    rewrite_references,
    with_parameter_defaults,
)


def doc(document, name=None):
    return parse(json.dumps(document), default_name=name)


def without(document, key):
    changed = copy.deepcopy(document)
    del changed["parameters"][key]
    return changed


def status_of(document, name, **options):
    return next(item for item in parameter_status(doc(document), **options) if item.name == name)


# Parameter status ------------------------------------------------------------------


def test_a_wrapper_value_satisfies_its_declaration():
    status = status_of(CODE_VIEW, "ticket_prefix")
    assert (status.satisfied, status.satisfied_by) == (True, "wrapper")


def test_connections_is_always_satisfied_since_the_deployment_tool_generates_it():
    assert status_of(CODE_VIEW, "$connections").satisfied_by == "generated"


def test_a_declaration_with_no_value_anywhere_is_unsatisfied_and_named():
    status = status_of(without(CODE_VIEW, "ticket_prefix"), "ticket_prefix")
    assert (status.satisfied, status.satisfied_by) == (False, "none")
    assert "code-view" in status.reason


def test_a_default_value_or_a_supplied_name_satisfies_it():
    defaulted = copy.deepcopy(BARE)
    defaulted["parameters"]["ticket_prefix"]["defaultValue"] = "SIR"
    assert status_of(defaulted, "ticket_prefix").satisfied_by == "default"
    assert status_of(BARE, "ticket_prefix", supplied=["ticket_prefix"]).satisfied_by == "supplied"


def test_a_wrapper_never_satisfies_a_secure_parameter():
    status = status_of(SECURE_CODE_VIEW, "api_secret")
    assert (status.secure, status.satisfied) == (True, False)
    assert "secret stays out" in status.reason


def test_a_bare_definitions_declarations_are_not_read_as_values():
    status = status_of(BARE, "ticket_prefix")
    assert not status.satisfied
    assert "bare definition" in status.reason


# The offline check -------------------------------------------------------------------


def rules(document, **options) -> list[str]:
    return [finding.rule for finding in check(doc(document), **options)]


def test_a_complete_definition_has_no_errors():
    assert rules(CODE_VIEW, connections=["servicenow", "azuresentinel"]) == []


def test_every_rule_fires_on_the_definition_that_breaks_it():
    assert rules(without(CODE_VIEW, "ticket_prefix"), connections=["x"]) == [
        "parameter-has-no-value"
    ]
    assert "supplied-parameter-not-declared" in rules(
        CODE_VIEW, supplied=["nope"], connections=["x"]
    )
    assert "connections-not-declared" in rules(ARM_RESOURCE, connections=["servicenow"])
    assert "callback-trigger-not-found" in rules(
        CODE_VIEW, connections=["x"], callback_trigger="When"
    )
    assert rules(CODE_VIEW, connections=["x"], callback_trigger="manual") == []


def test_warnings_for_what_deploys_then_surprises():
    assert rules(CODE_VIEW) == ["connections-unwired"]
    empty = {"definition": {"parameters": {}}, "parameters": {}}
    assert rules(empty) == ["no-trigger", "no-actions"]


def test_errors_come_before_warnings():
    findings = check(doc(without(CODE_VIEW, "ticket_prefix")))
    assert [finding.severity for finding in findings] == ["error", "warning"]


# Connections ---------------------------------------------------------------------------


def test_connections_are_read_with_their_ids_and_managed_identity():
    found = {item.key: item for item in connections_of(doc(CODE_VIEW))}
    assert found["servicenow"].connection_name == "api-servicenow"
    assert found["servicenow"].connection_id.endswith("/connections/api-servicenow")
    assert found["servicenow"].managed_identity
    assert not found["azuresentinel"].managed_identity


def test_a_bare_definition_resolves_no_connections():
    assert connections_of(doc(BARE)) == []


def references_by_key(document):
    return {item.key: item for item in connection_references(doc(document))}


def test_references_are_found_in_triggers_and_nested_actions():
    found = references_by_key(REFERENCES)
    assert len(found) == 2
    assert found["azuresentinel"].used_by == ("triggers/Incident",)
    assert found["servicenow"].used_by == ("Outer/Find",)
    assert all(item.wired is True for item in found.values())


def test_a_key_the_wrapper_does_not_wire_is_flagged():
    mismatched = copy.deepcopy(REFERENCES)
    wired = mismatched["parameters"]["$connections"]["value"]
    wired["service-now"] = wired.pop("servicenow")
    assert references_by_key(mismatched)["servicenow"].wired is False


def test_a_bare_definition_leaves_wired_unknown():
    found = references_by_key(REFERENCES["definition"])
    assert found
    assert {item.wired for item in found.values()} == {None}


def test_each_key_is_counted_once_per_action():
    twice = copy.deepcopy(REFERENCES)
    find = twice["definition"]["actions"]["Outer"]["actions"]["Find"]
    find["inputs"]["path"] = "@parameters('$connections')['servicenow']['connectionId']"
    assert references_by_key(twice)["servicenow"].used_by == ("Outer/Find",)


# Deploy order -------------------------------------------------------------------------


def test_a_leaf_deploys_first_its_caller_next_and_that_callers_caller_last():
    steps = deploy_order(
        [
            doc(dispatcher("dispatcher"), "router"),
            doc(dispatcher(None), "handler"),
            doc(dispatcher("handler"), "dispatcher"),
        ]
    )
    assert [(step.workflow, step.tier, step.depends_on) for step in steps] == [
        ("handler", 0, ()),
        ("dispatcher", 1, ("handler",)),
        ("router", 2, ("dispatcher",)),
    ]


def test_a_dispatch_cycle_has_no_order():
    with pytest.raises(InputError, match="cycle"):
        deploy_order([doc(dispatcher("beta"), "alpha"), doc(dispatcher("alpha"), "beta")])


def test_merely_naming_a_sibling_is_not_dispatching_to_it():
    uri = "https://management.azure.com/providers/Microsoft.Logic/workflows/handler/runs"
    watchdog = {
        "definition": {"actions": {"Probe": {"type": "Http", "inputs": {"uri": uri}}}},
        "parameters": {},
    }
    steps = {
        step.workflow: step
        for step in deploy_order([doc(dispatcher(None), "handler"), doc(watchdog, "watchdog")])
    }
    assert (steps["watchdog"].tier, steps["watchdog"].depends_on) == (0, ())


def test_a_dispatch_inside_a_switch_case_counts():
    call = dispatcher("handler")["definition"]["actions"]["Call"]
    switcher = {
        "definition": {
            "actions": {"Route": {"type": "Switch", "cases": {"mde": {"actions": {"Call": call}}}}}
        },
        "parameters": {},
    }
    steps = {
        step.workflow: step
        for step in deploy_order([doc(switcher, "switcher"), doc(dispatcher(None), "handler")])
    }
    assert steps["switcher"].depends_on == ("handler",)


def test_workflow_ids_match_case_insensitively_and_names_must_be_unique():
    shouting = dispatcher("HANDLER")
    steps = {
        step.workflow: step
        for step in deploy_order([doc(shouting, "caller"), doc(dispatcher(None), "handler")])
    }
    assert steps["caller"].depends_on == ("handler",)
    with pytest.raises(InputError, match="both called 'same'"):
        deploy_order([doc(BARE, "same"), doc(BARE, "same")])


# Compare -----------------------------------------------------------------------------


def test_a_definition_equals_itself_across_shapes():
    assert compare(doc(CODE_VIEW), doc(CODE_VIEW)) == []
    code_view = {
        "definition": ARM_RESOURCE["properties"]["definition"],
        "parameters": ARM_RESOURCE["properties"]["parameters"],
    }
    assert compare(doc(code_view), doc(ARM_RESOURCE), parameter_values=True) == []


def test_changes_additions_and_removals_are_reported_by_json_path():
    changed = copy.deepcopy(CODE_VIEW)
    changed["definition"]["actions"]["Compose"]["inputs"] = "other"
    changed["definition"]["actions"]["New"] = {"type": "Compose"}
    del changed["definition"]["contentVersion"]
    found = {item.path: item.change for item in compare(doc(CODE_VIEW), doc(changed))}
    assert found == {
        "definition.actions.Compose.inputs": "changed",
        "definition.actions.New": "added",
        "definition.contentVersion": "missing",
    }


def test_arrays_are_compared_by_index_and_values_optionally():
    left = copy.deepcopy(CODE_VIEW)
    right = copy.deepcopy(CODE_VIEW)
    right["parameters"]["category_map"]["value"].append({"contains": "Phish", "value": "Phishing"})
    assert compare(doc(left), doc(right)) == []
    found = compare(doc(left), doc(right), parameter_values=True)
    assert [(item.path, item.change) for item in found] == [
        ("parameters.category_map.value[1]", "added")
    ]


# Lifting between estates -----------------------------------------------------------


def test_defaults_are_copied_down_from_the_wrapper():
    definition, added = with_parameter_defaults(doc(CODE_VIEW))
    assert added == 3
    assert definition["parameters"]["ticket_prefix"]["defaultValue"] == "SIR"
    assert definition["parameters"]["retry_count"]["defaultValue"] == 3
    assert definition["parameters"]["$connections"] == {"type": "Object", "defaultValue": {}}
    # The result stands alone: a bare definition with nothing unsatisfied.
    assert all(item.satisfied for item in parameter_status(doc(definition)))


def test_defaults_never_copy_a_secret_and_respect_existing_ones():
    definition, added = with_parameter_defaults(doc(SECURE_CODE_VIEW))
    assert added == 0
    assert "defaultValue" not in definition["parameters"]["api_secret"]
    present = copy.deepcopy(CODE_VIEW)
    present["definition"]["parameters"]["ticket_prefix"]["defaultValue"] = "OLD"
    kept, _ = with_parameter_defaults(doc(present))
    assert kept["parameters"]["ticket_prefix"]["defaultValue"] == "OLD"
    forced, _ = with_parameter_defaults(doc(present), force=True)
    assert forced["parameters"]["ticket_prefix"]["defaultValue"] == "SIR"


def test_a_bare_definition_has_no_values_to_copy():
    with pytest.raises(InputError, match="bare definition"):
        with_parameter_defaults(doc(BARE))


def test_references_are_rewritten_in_order_and_nothing_else_changes():
    text = '{"id": "/subscriptions/aaa/resourceGroups/rg-old/x", "keep": "rg-older"}'
    rewritten = rewrite_references(
        text, [("/subscriptions/aaa", "/subscriptions/bbb"), ("rg-old/", "rg-new/")]
    )
    assert rewritten == '{"id": "/subscriptions/bbb/resourceGroups/rg-new/x", "keep": "rg-older"}'
    with pytest.raises(InputError, match="something to find"):
        rewrite_references(text, [("", "x")])
