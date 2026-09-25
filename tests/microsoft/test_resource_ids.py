import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.resource_ids import (
    looks_like_resource_id,
    parse_resource_id,
    try_parse_resource_id,
)

SUB = "12345678-1234-9876-4563-123456789012"
GROUP = f"/subscriptions/{SUB}/resourceGroups/resGroup1"


def test_terraforms_own_example_parses_to_the_same_parts():
    parsed = parse_resource_id(
        f"{GROUP}/providers/Microsoft.ApiManagement/service/service1/gateways/gateway1"
        "/hostnameConfigurations/config1"
    )
    found = parsed.as_dict()
    assert {
        key: value for key, value in found.items() if key not in {"id", "management_group_name"}
    } == {
        "full_resource_type": "Microsoft.ApiManagement/service/gateways/hostnameConfigurations",
        "parent_resources": {"gateways": "gateway1", "service": "service1"},
        "resource_group_name": "resGroup1",
        "resource_name": "config1",
        "resource_provider": "Microsoft.ApiManagement",
        "resource_scope": None,
        "resource_type": "hostnameConfigurations",
        "subscription_id": SUB,
    }
    assert parsed.scope == GROUP


def test_a_workspace_id_gives_its_group_subscription_and_name():
    parsed = parse_resource_id(
        f"{GROUP}/providers/Microsoft.OperationalInsights/workspaces/law-soc"
    )
    assert (parsed.subscription, parsed.resource_group, parsed.name) == (
        SUB,
        "resGroup1",
        "law-soc",
    )
    assert parsed.is_type("microsoft.operationalinsights/WORKSPACES")
    assert parsed.as_dict()["parent_resources"] == {}


def test_an_extension_resource_names_what_it_is_on():
    vm = f"{GROUP}/providers/Microsoft.Compute/virtualMachines/vm1"
    parsed = parse_resource_id(f"{vm}/providers/Microsoft.Security/assessments/a1")
    assert (parsed.type, parsed.name, parsed.scope) == ("Microsoft.Security/assessments", "a1", vm)
    assert parsed.parent is not None
    assert parsed.parent.type == "Microsoft.Compute/virtualMachines"
    assert parsed.as_dict()["resource_scope"] == vm


def test_subscriptions_groups_and_management_groups_are_ids_too():
    subscription = parse_resource_id(f"/subscriptions/{SUB.upper()}")
    assert (subscription.type, subscription.name, subscription.scope) == (
        "Microsoft.Resources/subscriptions",
        SUB,
        "",
    )
    group = parse_resource_id(f"{GROUP}/")
    assert (group.type, group.name, group.scope) == (
        "Microsoft.Resources/resourceGroups",
        "resGroup1",
        f"/subscriptions/{SUB}",
    )
    management = parse_resource_id("/providers/Microsoft.Management/managementGroups/mg-root")
    assert (management.type, management.management_group, management.scope) == (
        "Microsoft.Management/managementGroups",
        "mg-root",
        "",
    )
    assert management.as_dict()["management_group_name"] == "mg-root"
    assigned = parse_resource_id(
        "/providers/Microsoft.Management/managementGroups/mg-root"
        "/providers/Microsoft.Authorization/roleAssignments/ra1"
    )
    assert (assigned.management_group, assigned.scope) == ("mg-root", management.id)


def test_case_and_a_missing_leading_slash_are_forgiven():
    parsed = parse_resource_id(
        f"subscriptions/{SUB}/RESOURCEGROUPS/rg/providers/Microsoft.KeyVault/vaults/kv"
    )
    assert (parsed.id, parsed.resource_group) == (
        f"/subscriptions/{SUB}/RESOURCEGROUPS/rg/providers/Microsoft.KeyVault/vaults/kv",
        "rg",
    )
    assert looks_like_resource_id(" /Subscriptions/x")
    assert not looks_like_resource_id("law-soc")
    assert not looks_like_resource_id(SUB)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("law-soc", "starts /subscriptions/ or /providers/"),
        ("/subscriptions/not-a-guid", "is not a GUID"),
        (f"{GROUP}/providers/Microsoft.KeyVault/vaults", "has no name"),
        (f"{GROUP}/providers/Microsoft.KeyVault", "names no type"),
        (f"{GROUP}/extra/vaults/kv", "expected providers/NAMESPACE"),
        (f"{GROUP}/providers/Microsoft.KeyVault/vaults/../../x", "cannot be in one"),
        (f"{GROUP}/providers/Microsoft.KeyVault/vaults/kv?api-version=1", "cannot be in one"),
        (f"{GROUP}/providers/Microsoft.KeyVault/vaults/kv#x", "cannot be in one"),
        (f"{GROUP}//providers/Microsoft.KeyVault/vaults/kv", "cannot be in one"),
        (f"{GROUP}/providers/Microsoft.KeyVault/vaults/k v", "cannot be in one"),
    ],
    ids=[
        "name",
        "subscription",
        "no-name",
        "no-type",
        "not-providers",
        "dot-dot",
        "query",
        "fragment",
        "empty",
        "space",
    ],
)
def test_what_is_not_a_resource_id_is_refused_with_why(text, reason):
    with pytest.raises(InputError, match="not an Azure resource id") as caught:
        parse_resource_id(text)
    assert reason in str(caught.value) + (caught.value.hint or "")
    assert try_parse_resource_id(text) is None
