from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fakes import TENANT, StaticTokens, fake_session
from libre_devops_helpers.core.errors import (
    AmbiguousError,
    LdoError,
    NotFoundError,
)
from libre_devops_helpers.microsoft.clouds import USGOV
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.entra import EntraClient, expiring

GROUP_ID = "55555555-5555-5555-5555-555555555555"
DEVICE_OBJECT_ID = "66666666-6666-6666-6666-666666666666"


def device(name: str, object_id: str = DEVICE_OBJECT_ID) -> dict:
    return {"id": object_id, "displayName": name, "operatingSystem": "Linux"}


def group(name: str, object_id: str = GROUP_ID, dynamic: bool = False) -> dict:
    return {
        "id": object_id,
        "displayName": name,
        "groupTypes": ["DynamicMembership"] if dynamic else [],
        "securityEnabled": True,
    }


def entra(handler):
    session, adapter = fake_session(handler)
    tokens = StaticTokens()
    return EntraClient.create(tokens, TENANT, session=session), adapter, tokens


def query(request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request.url).query)


def test_find_devices_falls_back_to_the_short_name():
    def handler(request):
        if "'web01'" in unquote(request.url):
            return (200, {"value": [device("web01")]})
        return (200, {"value": []})

    client, adapter, tokens = entra(handler)
    found = client.find_devices("web01.corp.example.com")
    assert [d.display_name for d in found] == ["web01"]
    filters = [query(r)["$filter"][0] for r in adapter.requests]
    assert filters == ["displayName eq 'web01.corp.example.com'", "displayName eq 'web01'"]
    assert tokens.calls[0] == ("https://graph.microsoft.com", TENANT)


def test_get_group_by_name_must_be_unique():
    client, _, _ = entra(lambda request: (200, {"value": [group("Ring 1")]}))
    assert client.get_group("Ring 1").id == GROUP_ID

    two = [group("Ring 1"), group("Ring 1", "77777777-7777-7777-7777-777777777777")]
    client, _, _ = entra(lambda request: (200, {"value": two}))
    with pytest.raises(AmbiguousError, match="2 Entra groups"):
        client.get_group("Ring 1")

    client, _, _ = entra(lambda request: (200, {"value": []}))
    with pytest.raises(NotFoundError):
        client.get_group("Ring 9")


def test_get_group_by_id_maps_404_to_not_found():
    client, adapter, _ = entra(
        lambda request: (404, {"error": {"code": "Request_ResourceNotFound"}})
    )
    with pytest.raises(NotFoundError):
        client.get_group(GROUP_ID)
    assert urlsplit(adapter.requests[0].url).path == f"/v1.0/groups/{GROUP_ID}"


def test_device_groups_uses_a_transitive_cast_with_eventual_consistency():
    groups = [group("zeta", dynamic=True), group("Alpha")]
    client, adapter, _ = entra(lambda request: (200, {"value": groups}))
    result = client.device_groups(DEVICE_OBJECT_ID)
    assert [g.display_name for g in result] == ["Alpha", "zeta"]
    assert result[1].dynamic
    request = adapter.requests[0]
    path = f"/v1.0/devices/{DEVICE_OBJECT_ID}/transitiveMemberOf/microsoft.graph.group"
    assert urlsplit(request.url).path == path
    assert request.headers["ConsistencyLevel"] == "eventual"
    assert query(request)["$count"] == ["true"]


def test_group_devices_direct_uses_members():
    client, adapter, _ = entra(lambda request: (200, {"value": [device("db01")]}))
    assert [d.display_name for d in client.group_devices(GROUP_ID, transitive=False)] == ["db01"]
    path = f"/v1.0/groups/{GROUP_ID}/members/microsoft.graph.device"
    assert urlsplit(adapter.requests[0].url).path == path


def test_object_ids_are_validated_before_building_a_path():
    client, adapter, _ = entra(lambda request: (200, {"value": []}))
    with pytest.raises(LdoError, match="not an Entra object id"):
        client.device_groups("../users")
    assert adapter.requests == []


USER_ID = "88888888-8888-8888-8888-888888888888"


def user(upn: str = "ana@example.com", object_id: str = USER_ID) -> dict:
    return {"id": object_id, "displayName": "Ana", "userPrincipalName": upn, "accountEnabled": True}


def test_get_user_by_upn_encodes_a_guest_upn():
    client, adapter, _ = entra(lambda request: (200, user("ana_x.com#EXT#@example.com")))
    found = client.get_user("ana_x.com#EXT#@example.com")
    assert found.id == USER_ID
    assert urlsplit(adapter.requests[0].url).path == "/v1.0/users/ana_x.com%23EXT%23@example.com"


def test_get_user_by_display_name_must_be_unique():
    two = [user(), user("ana2@example.com", "99999999-9999-9999-9999-999999999999")]
    client, _, _ = entra(lambda request: (200, {"value": two}))
    with pytest.raises(AmbiguousError, match="2 Entra users"):
        client.get_user("Ana")


def test_user_groups_uses_transitive_member_of():
    client, adapter, _ = entra(lambda request: (200, {"value": [group("Admins")]}))
    assert [g.display_name for g in client.user_groups(USER_ID)] == ["Admins"]
    path = f"/v1.0/users/{USER_ID}/transitiveMemberOf/microsoft.graph.group"
    assert urlsplit(adapter.requests[0].url).path == path


def test_group_members_of_every_kind_reads_the_odata_type():
    members = [
        {
            "@odata.type": "#microsoft.graph.user",
            "id": USER_ID,
            "displayName": "Ana",
            "userPrincipalName": "ana@example.com",
        },
        {
            "@odata.type": "#microsoft.graph.device",
            "id": DEVICE_OBJECT_ID,
            "displayName": "web01",
            "operatingSystem": "Linux",
        },
    ]
    client, adapter, _ = entra(lambda request: (200, {"value": members}))
    found = client.group_members(GROUP_ID)
    assert [(m.kind, m.detail) for m in found] == [("device", "Linux"), ("user", "ana@example.com")]
    assert urlsplit(adapter.requests[0].url).path == f"/v1.0/groups/{GROUP_ID}/transitiveMembers"
    assert "ConsistencyLevel" not in adapter.requests[0].headers


def test_group_members_of_one_kind_casts_with_eventual_consistency():
    client, adapter, _ = entra(lambda request: (200, {"value": [user()]}))
    found = client.group_members(GROUP_ID, transitive=False, kind="user")
    assert found[0].kind == "user"
    request = adapter.requests[0]
    assert urlsplit(request.url).path == f"/v1.0/groups/{GROUP_ID}/members/microsoft.graph.user"
    assert request.headers["ConsistencyLevel"] == "eventual"


def test_user_roles_reads_active_and_eligible_roles():
    active = {"id": "r1", "displayName": "Global Reader", "roleTemplateId": "t1"}
    eligible = {
        "roleDefinitionId": "t2",
        "directoryScopeId": "/",
        "roleDefinition": {"displayName": "Security Administrator", "templateId": "t2"},
        "scheduleInfo": {"expiration": {"endDateTime": "2027-01-01T00:00:00Z"}},
    }

    def handler(request):
        if "roleEligibilitySchedules" in request.url:
            return (200, {"value": [eligible]})
        return (200, {"value": [active]})

    client, adapter, _ = entra(handler)
    report = client.user_roles(USER_ID)
    assert [(r.role_name, r.state) for r in report.active] == [("Global Reader", "active")]
    assert [(r.role_name, r.state) for r in report.eligible] == [
        ("Security Administrator", "eligible")
    ]
    assert report.eligible[0].ends is not None
    assert query(adapter.requests[1])["$filter"] == [f"principalId eq '{USER_ID}'"]


def test_user_roles_reports_unreadable_eligibility_instead_of_failing():
    def handler(request):
        if "roleEligibilitySchedules" in request.url:
            return (403, {"error": {"code": "Forbidden", "message": "needs P2"}})
        return (200, {"value": []})

    client, _, _ = entra(handler)
    report = client.user_roles(USER_ID)
    assert report.eligible is None
    assert "needs P2" in (report.eligible_error or "")


def test_sign_ins_build_one_filter_and_stop_at_the_limit():
    page = {
        "value": [{"id": str(n), "status": {"errorCode": 50126}} for n in range(3)],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/auditLogs/signIns?page=2",
    }
    client, adapter, _ = entra(lambda request: (200, page))
    since = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    events = client.sign_ins(user="ana@example.com", since=since, failures_only=True, limit=2)
    assert [event.id for event in events] == ["0", "1"]
    assert not events[0].succeeded
    assert len(adapter.requests) == 1
    assert query(adapter.requests[0])["$filter"] == [
        "userPrincipalName eq 'ana@example.com' and createdDateTime ge 2026-09-23T12:00:00Z"
        " and status/errorCode ne 0"
    ]


def test_app_credentials_flatten_secrets_and_certificates_and_expiring_filters():
    now = datetime(2026, 9, 24, tzinfo=UTC)
    app = {
        "id": "o1",
        "appId": "a1",
        "displayName": "billing-api",
        "passwordCredentials": [
            {"keyId": "k1", "displayName": "ci", "endDateTime": "2026-10-01T00:00:00Z"},
            {"keyId": "k2", "displayName": "old", "endDateTime": "2026-09-01T00:00:00Z"},
        ],
        "keyCredentials": [
            {"keyId": "k3", "displayName": "CN=billing", "endDateTime": "2028-01-01T00:00:00Z"}
        ],
    }
    client, adapter, _ = entra(lambda request: (200, {"value": [app]}))
    found = client.app_credentials()
    assert [(c.kind, c.name) for c in found] == [
        ("secret", "ci"),
        ("secret", "old"),
        ("certificate", "CN=billing"),
    ]
    assert found[0].days_left(now) == 7
    soon = expiring(found, timedelta(days=30), now=now)
    assert [c.name for c in soon] == ["old", "ci"]
    assert [
        c.name for c in expiring(found, timedelta(days=30), now=now, include_expired=False)
    ] == ["ci"]
    assert urlsplit(adapter.requests[0].url).path == "/v1.0/applications"


def test_ca_policies_are_flattened():
    policy = {
        "id": "p1",
        "displayName": "Require MFA for admins",
        "state": "enabledForReportingButNotEnforced",
        "conditions": {
            "users": {"includeRoles": ["62e90394"], "excludeUsers": ["break-glass"]},
            "applications": {"includeApplications": ["All"]},
            "clientAppTypes": ["all"],
        },
        "grantControls": {"operator": "OR", "builtInControls": ["mfa"]},
        "sessionControls": {"signInFrequency": {"value": 4}, "persistentBrowser": None},
    }
    client, _, _ = entra(lambda request: (200, {"value": [policy]}))
    found = client.ca_policies()[0]
    assert found.include_roles == ("62e90394",)
    assert found.include_applications == ("All",)
    assert found.grant_controls == ("mfa",)
    assert found.session_controls == ("signInFrequency",)


def test_find_principal_searches_groups_service_principals_and_users():
    def handler(request):
        if "/v1.0/servicePrincipals" in request.url:
            return (200, {"value": [{"id": USER_ID, "displayName": "deployer", "appId": "a1"}]})
        return (200, {"value": []})

    client, _, _ = entra(handler)
    found = client.find_principal("deployer")
    assert (found.kind, found.detail) == ("servicePrincipal", "a1")


def test_a_profile_in_another_cloud_uses_its_graph_host():
    session, adapter = fake_session(lambda request: (200, {"value": []}))
    profile = Profile("gov", TENANT, cloud=USGOV)
    tokens = StaticTokens()
    EntraClient.for_profile(profile, tokens, session=session).find_devices("web01")
    assert urlsplit(adapter.requests[0].url).netloc == "graph.microsoft.us"
    assert tokens.calls[0] == ("https://graph.microsoft.us", TENANT)
