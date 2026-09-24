from urllib.parse import unquote, urlsplit

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.pim import ME, RULES, query
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import NotFoundError
from libre_devops_helpers.microsoft.pim import GraphPimClient

GLOBAL_ADMIN = "62e90394-69f5-4237-9190-012177145e10"

GROUP = "55555555-5555-5555-5555-555555555555"


def graph(handler):
    session, adapter = fake_session(handler)
    return GraphPimClient.create(StaticTokens(), TENANT, session=session), adapter


def graph_tenant(request):
    path = unquote(urlsplit(request.url).path)
    if path.endswith("/roleDefinitions"):
        return (200, {"value": [{"id": GLOBAL_ADMIN, "displayName": "Global Administrator"}]})
    if path.startswith(f"/v1.0/groups/{GROUP}"):
        return (200, {"displayName": "Platform Admins"})
    if "roleEligibilityScheduleInstances" in path:
        return (
            200,
            {
                "value": [
                    {
                        "roleDefinitionId": GLOBAL_ADMIN,
                        "directoryScopeId": "/",
                        "memberType": "Direct",
                        "endDateTime": "2027-01-01T00:00:00Z",
                    }
                ]
            },
        )
    if "roleAssignmentScheduleInstances" in path:
        return (
            200,
            {
                "value": [
                    {
                        "roleDefinitionId": GLOBAL_ADMIN,
                        "assignmentType": "Activated",
                        "endDateTime": "2026-09-24T18:00:00Z",
                    }
                ]
            },
        )
    if "roleAssignmentScheduleRequests" in path or "assignmentScheduleRequests" in path:
        return (
            200,
            {
                "value": [
                    {
                        "id": "r1",
                        "action": "selfActivate",
                        "status": "PendingApproval",
                        "roleDefinitionId": GLOBAL_ADMIN,
                        "accessId": "member",
                        "groupId": GROUP,
                        "createdDateTime": "2026-09-24T09:00:00Z",
                        "justification": "change 7",
                        "scheduleInfo": {"expiration": {"duration": "PT2H"}},
                        "ticketInfo": {"ticketNumber": "CHG7"},
                    },
                    {
                        "id": "r0",
                        "action": "selfActivate",
                        "status": "Provisioned",
                        "roleDefinitionId": GLOBAL_ADMIN,
                        "createdDateTime": "2026-09-20T09:00:00Z",
                    },
                ]
            },
        )
    if "eligibilityScheduleInstances" in path or "assignmentScheduleInstances" in path:
        return (200, {"value": [{"accessId": "owner", "groupId": GROUP, "memberType": "Direct"}]})
    if path == "/v1.0/policies/roleManagementPolicyAssignments":
        return (200, {"value": [{"policy": {"rules": RULES}}]})
    raise AssertionError(f"unexpected {request.url}")


def test_my_entra_roles_use_filter_by_current_user_and_name_the_role_once():
    client, adapter = graph(graph_tenant)
    eligible = client.role_eligible()
    active = client.role_active()
    assert eligible[0].role == "Global Administrator"
    assert eligible[0].ends is not None
    assert active[0].activated
    paths = [unquote(urlsplit(r.url).path) for r in adapter.requests]
    assert paths[0].endswith(
        "/roleEligibilityScheduleInstances/filterByCurrentUser(on='principal')"
    )
    assert sum(path.endswith("/roleDefinitions") for path in paths) == 1


def test_someone_elses_entra_roles_use_a_principal_filter():
    client, adapter = graph(graph_tenant)
    client.role_eligible(principal_id=ME)
    request = next(r for r in adapter.requests if "roleEligibilityScheduleInstances" in r.url)
    assert query(request)["$filter"] == f"principalId eq '{ME}'"


def test_entra_requests_waiting_on_me_use_the_approver_filter_newest_first():
    client, adapter = graph(graph_tenant)
    found = client.role_requests(approver=True)
    assert [item.id for item in found] == ["r1", "r0"]
    assert found[0].pending
    assert (found[0].duration, found[0].ticket) == ("PT2H", "CHG7")
    assert any("filterByCurrentUser(on='approver')" in unquote(r.url) for r in adapter.requests)


def test_entra_settings_resolve_the_role_by_name_and_expand_the_rules():
    client, adapter = graph(graph_tenant)
    found = client.role_settings("global administrator")
    assert found.role == "Global Administrator"
    assert found.eligible_expiry == "permanent allowed"
    assert found.active_expiry == "P180D"
    policy = next(r for r in adapter.requests if "roleManagementPolicyAssignments" in r.url)
    assert f"roleDefinitionId eq '{GLOBAL_ADMIN}'" in query(policy)["$filter"]
    assert query(policy)["$expand"] == "policy($expand=rules)"
    with pytest.raises(NotFoundError):
        client.role_settings("Chief Unicorn Officer")


def test_group_assignments_name_the_group_and_cache_it():
    client, adapter = graph(graph_tenant)
    eligible = client.group_eligible()
    active = client.group_active()
    assert (eligible[0].role, eligible[0].scope) == ("owner", "Platform Admins")
    assert active[0].scope == "Platform Admins"
    assert sum(f"/v1.0/groups/{GROUP}" in r.url for r in adapter.requests) == 1


def test_group_requests_show_the_access_and_the_group():
    client, _ = graph(graph_tenant)
    found = client.group_requests()
    assert (found[0].role, found[0].scope) == ("member", "Platform Admins")


def test_group_settings_ask_for_members_or_owners():
    client, adapter = graph(graph_tenant)
    found = client.group_settings(GROUP, "owner")
    assert (found.area, found.role, found.scope) == ("groups", "owner", "Platform Admins")
    policy = next(r for r in adapter.requests if "roleManagementPolicyAssignments" in r.url)
    assert query(policy)["$filter"] == (
        f"scopeId eq '{GROUP}' and scopeType eq 'Group' and roleDefinitionId eq 'owner'"
    )


def test_a_group_name_that_cannot_be_read_falls_back_to_its_id():
    def handler(request):
        if "/v1.0/groups/" in request.url:
            return (403, {"error": {"code": "Forbidden"}})
        return graph_tenant(request)

    client, _ = graph(handler)
    assert client.group_eligible()[0].scope == GROUP


def test_a_request_without_a_group_never_calls_the_groups_collection():
    client, adapter = graph(graph_tenant)
    client.group_requests()
    assert not any(urlsplit(r.url).path == "/v1.0/groups/" for r in adapter.requests)
