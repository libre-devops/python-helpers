import re

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.microsoft.workspaces import workspace_ref

GUID = "AbAbAbAb-abab-abab-abab-abababababab"
RESOURCE = (
    "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-soc"
    "/providers/Microsoft.OperationalInsights/workspaces/law-soc"
)


def test_each_of_a_workspaces_three_names_is_told_apart():
    assert workspace_ref(f" {GUID} ").kind == "workspace id"
    assert workspace_ref(GUID).value == GUID.lower()
    by_id = workspace_ref(RESOURCE)
    assert (by_id.kind, by_id.value) == ("resource id", RESOURCE)
    assert by_id.resource_id is not None
    assert by_id.resource_id.name == "law-soc"
    assert workspace_ref("law-soc").kind == "name"


def test_another_kind_of_resource_id_says_what_it_is():
    vault = RESOURCE.replace(
        "Microsoft.OperationalInsights/workspaces/law-soc", "Microsoft.KeyVault/vaults/kv"
    )
    with pytest.raises(
        InputError, match=re.escape("resource id of a Microsoft.KeyVault/vaults, not of a Log")
    ):
        workspace_ref(vault)
    group = RESOURCE.split("/providers/")[0]
    with pytest.raises(
        InputError, match=re.escape("resource id of a Microsoft.Resources/resourceGroups")
    ):
        workspace_ref(group)


@pytest.mark.parametrize("text", ["", "a", "law soc", "-law", "x" * 64, "law';drop"])
def test_what_is_none_of_them_is_refused_with_all_three_named(text):
    with pytest.raises(InputError) as caught:
        workspace_ref(text)
    assert "Workspace ID (a GUID" in (caught.value.hint or "")
    assert "resource id" in (caught.value.hint or "")
