from urllib.parse import parse_qs, urlsplit

import pytest

from fakes.http import fake_session, json_body
from fakes.ids import OTHER_TENANT, SUBSCRIPTION, TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import AmbiguousError, ApiError, LdoError, NotFoundError
from libre_devops_helpers.microsoft.azure import AzureClient
from libre_devops_helpers.microsoft.workspaces import workspace_ref

PRINCIPAL = "88888888-8888-8888-8888-888888888888"

READER = f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7"


def azure(handler):
    session, adapter = fake_session(handler)
    tokens = StaticTokens()
    return AzureClient.create(tokens, TENANT, session=session), adapter, tokens


def query(request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request.url).query)


def test_tokens_are_for_the_arm_resource_with_its_trailing_slash():
    client, _, tokens = azure(lambda request: (200, {"value": []}))
    client.subscriptions()
    assert tokens.calls[0] == ("https://management.azure.com/", TENANT)


def test_subscriptions_follow_next_link_and_keep_the_tenant():
    def handler(request):
        if "page=2" in request.url:
            return (
                200,
                {"value": [{"subscriptionId": "b", "displayName": "B", "tenantId": TENANT}]},
            )
        return (
            200,
            {
                "value": [
                    {"subscriptionId": "a", "displayName": "A", "tenantId": OTHER_TENANT},
                ],
                "nextLink": "https://management.azure.com/subscriptions?page=2",
            },
        )

    client, adapter, _ = azure(handler)
    assert [s.id for s in client.subscriptions(TENANT)] == ["b"]
    assert query(adapter.requests[0])["api-version"] == ["2022-12-01"]


def test_resource_graph_pages_with_skip_tokens_up_to_the_limit():
    pages = iter(
        [
            {"data": [{"name": "kv1"}, {"name": "kv2"}], "$skipToken": "t1"},
            {"data": [{"name": "kv3", "location": "uksouth"}], "$skipToken": "t2"},
        ]
    )
    client, adapter, _ = azure(lambda request: (200, next(pages)))
    result = client.resource_graph("resources", subscriptions=[SUBSCRIPTION], limit=3)
    assert [row["name"] for row in result.rows] == ["kv1", "kv2", "kv3"]
    assert result.columns == ("name", "location")
    assert result.truncated
    first, second = (json_body(request) for request in adapter.requests)
    assert first["subscriptions"] == [SUBSCRIPTION]
    assert first["options"]["resultFormat"] == "objectArray"
    assert "$skipToken" not in first["options"]
    assert second["options"]["$skipToken"] == "t1"
    assert second["options"]["$top"] == 1


def test_role_assignments_use_assigned_to_dedupe_and_resolve_role_names():
    assignment = {
        "id": "/subscriptions/s/providers/Microsoft.Authorization/roleAssignments/r1",
        "properties": {
            "scope": "/",
            "roleDefinitionId": READER,
            "principalId": "group-id",
            "principalType": "Group",
        },
    }

    def handler(request):
        if "roleDefinitions" in request.url:
            return (200, {"properties": {"roleName": "Reader"}})
        return (200, {"value": [assignment]})

    client, adapter, _ = azure(handler)
    other = "99999999-9999-9999-9999-999999999999"
    found = client.role_assignments(PRINCIPAL, [SUBSCRIPTION, other])
    assert [(a.role_name, a.principal_type) for a in found] == [("Reader", "Group")]
    listing = [r for r in adapter.requests if "roleAssignments" in r.url]
    assert query(listing[0])["$filter"] == [f"assignedTo('{PRINCIPAL}')"]
    # The role name is looked up once, however many assignments use it.
    assert sum("roleDefinitions" in r.url for r in adapter.requests) == 1


def test_role_assignments_validate_ids_before_building_paths():
    client, adapter, _ = azure(lambda request: (200, {"value": []}))
    with pytest.raises(LdoError, match="not a principal id"):
        client.role_assignments("ana@example.com", [SUBSCRIPTION])
    with pytest.raises(LdoError, match="not a subscription id"):
        client.role_assignments(PRINCIPAL, ["../x"])
    assert adapter.requests == []


def test_secure_score_is_none_where_defender_for_cloud_has_none():
    client, _, _ = azure(lambda request: (404, {"error": {"code": "NotFound"}}))
    assert client.secure_score(SUBSCRIPTION) is None
    client, _, _ = azure(
        lambda request: (
            200,
            {"properties": {"score": {"current": 12.5, "max": 40, "percentage": 0.3125}}},
        )
    )
    score = client.secure_score(SUBSCRIPTION)
    assert (score.current, score.max) == (12.5, 40.0)


def test_controls_sort_by_points_lost_and_assessments_by_severity():
    controls = [
        {"properties": {"displayName": "MFA", "score": {"current": 0, "max": 10}}},
        {"properties": {"displayName": "Encrypt", "score": {"current": 3, "max": 4}}},
    ]
    assessments = [
        {
            "id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.Compute"
            "/virtualMachines/vm1/providers/Microsoft.Security/assessments/a1",
            "properties": {
                "displayName": "Low thing",
                "status": {"code": "Unhealthy"},
                "metadata": {"severity": "Low"},
            },
        },
        {
            "id": "a2",
            "properties": {
                "displayName": "High thing",
                "status": {"code": "Unhealthy"},
                "metadata": {"severity": "High"},
            },
        },
        {"id": "a3", "properties": {"displayName": "Fine", "status": {"code": "Healthy"}}},
    ]

    def handler(request):
        if "secureScoreControls" in request.url:
            return (200, {"value": controls})
        return (200, {"value": assessments})

    client, _, _ = azure(handler)
    assert [c.name for c in client.secure_score_controls(SUBSCRIPTION)] == ["MFA", "Encrypt"]
    found = client.assessments(SUBSCRIPTION)
    assert [a.name for a in found] == ["High thing", "Low thing"]
    assert found[1].resource_id.endswith("/virtualMachines/vm1")
    assert len(client.assessments(SUBSCRIPTION, unhealthy_only=False)) == 3


def test_defender_plans_report_their_tier():
    plans = {
        "value": [
            {"name": "VirtualMachines", "properties": {"pricingTier": "Standard", "subPlan": "P2"}},
            {"name": "Api", "properties": {"pricingTier": "Free"}},
        ]
    }
    client, _, _ = azure(lambda request: (200, plans))
    found = client.defender_plans(SUBSCRIPTION)
    assert [(p.name, p.enabled) for p in found] == [("Api", False), ("VirtualMachines", True)]


WORKSPACE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-soc"
    "/providers/Microsoft.OperationalInsights/workspaces/law-soc"
)
CUSTOMER_ID = "abababab-abab-abab-abab-abababababab"
LAW = {
    "id": WORKSPACE_ID,
    "name": "law-soc",
    "location": "uksouth",
    "properties": {"customerId": CUSTOMER_ID.upper()},
}


def test_a_workspace_is_read_by_its_resource_id():
    client, adapter, _ = azure(lambda request: (200, LAW))
    found = client.workspace(workspace_ref(WORKSPACE_ID))
    assert (found.name, found.workspace_id) == ("law-soc", CUSTOMER_ID)
    assert (found.subscription_id, found.resource_group, found.location) == (
        SUBSCRIPTION,
        "rg-soc",
        "uksouth",
    )
    assert urlsplit(adapter.requests[0].url).path == WORKSPACE_ID
    assert query(adapter.requests[0])["api-version"] == ["2023-09-01"]


def test_a_workspace_that_is_not_there_is_not_found():
    client, _, _ = azure(lambda request: (404, {"error": {"code": "ResourceNotFound"}}))
    with pytest.raises(NotFoundError, match="no Log Analytics workspace at"):
        client.workspace(workspace_ref(WORKSPACE_ID))


def test_other_failures_reading_a_workspace_are_left_as_they_are():
    client, _, _ = azure(lambda request: (403, {"error": {"code": "AuthorizationFailed"}}))
    with pytest.raises(ApiError) as caught:
        client.workspace(workspace_ref(WORKSPACE_ID))
    assert caught.value.status == 403


@pytest.mark.parametrize(
    ("given", "clause"),
    [("law-soc", "name =~ 'law-soc'"), (CUSTOMER_ID, f"properties.customerId =~ '{CUSTOMER_ID}'")],
    ids=["name", "workspace-id"],
)
def test_a_workspace_is_found_by_name_or_workspace_id_with_resource_graph(given, clause):
    client, adapter, _ = azure(lambda request: (200, {"data": [LAW]}))
    found = client.workspace(workspace_ref(given), subscriptions=[SUBSCRIPTION])
    assert found.id == WORKSPACE_ID
    body = json_body(adapter.requests[0])
    assert body["query"] == (
        f"resources | where type =~ 'Microsoft.OperationalInsights/workspaces' and {clause}"
        " | project id, name, location, properties"
    )
    assert body["subscriptions"] == [SUBSCRIPTION]


def test_a_workspace_name_matching_nothing_or_several_says_so():
    client, _, _ = azure(lambda request: (200, {"data": []}))
    with pytest.raises(NotFoundError, match="no Log Analytics workspace with the name"):
        client.workspace(workspace_ref("law-soc"))
    other = {**LAW, "id": WORKSPACE_ID.replace("rg-soc", "rg-dev")}
    client, _, _ = azure(lambda request: (200, {"data": [LAW, other]}))
    with pytest.raises(AmbiguousError, match="2 workspaces are named 'law-soc'"):
        client.workspace(workspace_ref("law-soc"))


def test_a_workspace_without_a_workspace_id_is_refused():
    client, _, _ = azure(lambda request: (200, {**LAW, "properties": {}}))
    with pytest.raises(NotFoundError, match="no Workspace ID"):
        client.workspace(workspace_ref(WORKSPACE_ID))
