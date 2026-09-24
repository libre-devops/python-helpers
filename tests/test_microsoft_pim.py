from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fakes import SUBSCRIPTION, TENANT, StaticTokens, fake_session
from libre_devops_helpers.core.errors import LdoError, NotFoundError
from libre_devops_helpers.microsoft.pim import AzurePimClient, GraphPimClient, settings_from_rules

ME = "88888888-8888-8888-8888-888888888888"
GLOBAL_ADMIN = "62e90394-69f5-4237-9190-012177145e10"
GROUP = "55555555-5555-5555-5555-555555555555"
SCOPE = f"/subscriptions/{SUBSCRIPTION}"

RULES = [
    {
        "id": "Expiration_EndUser_Assignment",
        "isExpirationRequired": True,
        "maximumDuration": "PT8H",
    },
    {
        "id": "Enablement_EndUser_Assignment",
        "enabledRules": ["MultiFactorAuthentication", "Justification"],
    },
    {
        "id": "Approval_EndUser_Assignment",
        "setting": {
            "isApprovalRequired": True,
            "approvalStages": [{"primaryApprovers": [{"description": "Security Leads"}]}],
        },
    },
    {"id": "AuthenticationContext_EndUser_Assignment", "isEnabled": True, "claimValue": "c1"},
    {
        "id": "Expiration_Admin_Eligibility",
        "isExpirationRequired": False,
        "maximumDuration": "P365D",
    },
    {"id": "Expiration_Admin_Assignment", "isExpirationRequired": True, "maximumDuration": "P180D"},
]


def query(request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(request.url).query).items()}


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


def graph(handler):
    session, adapter = fake_session(handler)
    return GraphPimClient.create(StaticTokens(), TENANT, session=session), adapter


# Azure resources ------------------------------------------------------------------


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


# Entra roles ---------------------------------------------------------------------


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


# PIM for Groups ------------------------------------------------------------------


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


# Rules ---------------------------------------------------------------------------


def test_settings_from_rules_read_arm_and_graph_rules_alike():
    found = settings_from_rules("entra", "Role", "/", RULES)
    assert found.requires_justification
    assert not found.requires_ticket
    assert found.authentication_context == "c1"
    empty = settings_from_rules("azure", "Role", "/", [])
    assert (empty.max_activation, empty.requires_approval, empty.eligible_expiry) == ("", False, "")


def test_a_request_without_a_group_never_calls_the_groups_collection():
    client, adapter = graph(graph_tenant)
    client.group_requests()
    assert not any(urlsplit(r.url).path == "/v1.0/groups/" for r in adapter.requests)
