from urllib.parse import urlsplit

import pytest

from fakes.http import fake_session
from fakes.ids import SUBSCRIPTION, TENANT
from fakes.pim import ME, RULES, query
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import LdoError, NotFoundError
from libre_devops_helpers.microsoft.pim import AzurePimClient

SCOPE = f"/subscriptions/{SUBSCRIPTION}"


def arm_instance(role: str, *, assignment_type: str = "", ends: str | None = None, member="Direct"):
    return {
        "id": f"/providers/Microsoft.Authorization/x/{role}",
        "properties": {
            "scope": SCOPE,
            "principalId": ME,
            "memberType": member,
            "assignmentType": assignment_type,
            "startDateTime": "2026-09-01T00:00:00Z",
            "endDateTime": ends,
            "expandedProperties": {
                "principal": {"displayName": "Ana"},
                "roleDefinition": {"displayName": role},
                "scope": {"displayName": "libre-devops-dev"},
            },
        },
    }


def azure(handler):
    session, adapter = fake_session(handler)
    return AzurePimClient.create(StaticTokens(), TENANT, session=session), adapter


def test_my_azure_eligibility_is_asked_once_at_the_root_as_target():
    client, adapter = azure(
        lambda request: (200, {"value": [arm_instance("Owner", member="Group")]})
    )
    found = client.eligible()
    assert [(item.role, item.scope, item.member_type) for item in found] == [
        ("Owner", "libre-devops-dev", "Group")
    ]
    request = adapter.requests[0]
    assert (
        urlsplit(request.url).path
        == "/providers/Microsoft.Authorization/roleEligibilityScheduleInstances"
    )
    assert query(request) == {"api-version": "2020-10-01", "$filter": "asTarget()"}


def test_someone_elses_azure_roles_are_searched_per_scope_and_deduplicated():
    reply = {"value": [arm_instance("Reader", assignment_type="Assigned")]}
    client, adapter = azure(lambda request: (200, reply))
    other = "/subscriptions/99999999-9999-9999-9999-999999999999"
    found = client.active(principal_id=ME, scopes=[SCOPE, other])
    assert len(found) == 1
    assert found[0].permanent
    assert not found[0].activated
    assert [query(r)["$filter"] for r in adapter.requests] == [f"assignedTo('{ME}')"] * 2
    assert urlsplit(adapter.requests[1].url).path.startswith(other)


def test_a_named_principal_needs_a_real_id_and_a_scope():
    client, adapter = azure(lambda request: (200, {"value": []}))
    with pytest.raises(LdoError, match="not an object id"):
        client.eligible(principal_id="ana@example.com", scopes=[SCOPE])
    with pytest.raises(LdoError, match="not an Azure scope"):
        client.eligible(principal_id=ME, scopes=["../../evil"])
    with pytest.raises(LdoError, match="at least one scope"):
        client.eligible(principal_id=ME)
    assert adapter.requests == []


def test_azure_requests_use_requestor_or_approver_filters():
    request_item = {
        "id": "r1",
        "properties": {
            "requestType": "SelfActivate",
            "status": "PendingApproval",
            "principalId": ME,
            "justification": "incident 42",
            "createdOn": "2026-09-24T10:00:00Z",
            "scheduleInfo": {"expiration": {"type": "AfterDuration", "duration": "PT4H"}},
            "expandedProperties": {"roleDefinition": {"displayName": "Owner"}},
        },
    }
    client, adapter = azure(lambda request: (200, {"value": [request_item]}))
    mine = client.requests()
    assert mine[0].pending
    assert (mine[0].action, mine[0].duration, mine[0].role) == ("SelfActivate", "PT4H", "Owner")
    client.requests(approver=True)
    assert [query(r)["$filter"] for r in adapter.requests] == ["asRequestor()", "asApprover()"]


def test_azure_settings_find_the_role_then_read_its_effective_rules():
    def handler(request):
        if urlsplit(request.url).path.endswith("/roleDefinitions"):
            assert query(request)["$filter"] == "roleName eq 'Owner'"
            return (
                200,
                {"value": [{"id": f"{SCOPE}/providers/Microsoft.Authorization/roleDefinitions/o"}]},
            )
        return (200, {"value": [{"properties": {"effectiveRules": RULES}}]})

    client, _ = azure(handler)
    found = client.settings("Owner", SCOPE)
    assert (found.max_activation, found.requires_mfa, found.requires_approval) == (
        "PT8H",
        True,
        True,
    )
    assert found.approvers == ("Security Leads",)


def test_azure_settings_for_an_unknown_role_say_so():
    client, _ = azure(lambda request: (200, {"value": []}))
    with pytest.raises(NotFoundError, match="no Azure role is named"):
        client.settings("Nope", SCOPE)
