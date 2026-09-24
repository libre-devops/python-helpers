from fakes.pim import RULES
from libre_devops_helpers.microsoft.pim import settings_from_rules


def test_settings_from_rules_read_arm_and_graph_rules_alike():
    found = settings_from_rules("entra", "Role", "/", RULES)
    assert found.requires_justification
    assert not found.requires_ticket
    assert found.authentication_context == "c1"
    empty = settings_from_rules("azure", "Role", "/", [])
    assert (empty.max_activation, empty.requires_approval, empty.eligible_expiry) == ("", False, "")
