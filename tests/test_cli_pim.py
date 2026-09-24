"""The pim commands, end to end over a fake tenant: per-area results, warnings and exit codes."""

import json
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from typer.testing import CliRunner

from fakes import (
    SUBSCRIPTION,
    TENANT,
    account_json,
    az_runner,
    fake_session,
    graph_claims,
    make_jwt,
)
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.runtime import Runtime

ME = "88888888-8888-8888-8888-888888888888"
GROUP = "55555555-5555-5555-5555-555555555555"
ROLE = "62e90394-69f5-4237-9190-012177145e10"
CONFIG = f"""
[microsoft]
default_profile = "tenant"

[microsoft.profiles.tenant]
tenant_id = "{TENANT}"
"""
NO_SCOPE = (
    403,
    {
        "error": {
            "code": "UnknownError",
            "message": '{"errorCode":"PermissionScopeNotGranted","message":"missing scope"}',
        }
    },
)
NO_LICENCE = (
    400,
    {"error": {"code": "AadPremiumLicenseRequired", "message": "The tenant needs P2"}},
)
RULES = [
    {"id": "Expiration_EndUser_Assignment", "maximumDuration": "PT8H"},
    {"id": "Enablement_EndUser_Assignment", "enabledRules": ["MultiFactorAuthentication"]},
    {"id": "Approval_EndUser_Assignment", "setting": {"isApprovalRequired": False}},
]

runner = CliRunner()


def az_responder(args):
    if args[:2] == ["account", "get-access-token"]:
        resource = args[args.index("--resource") + 1]
        token = make_jwt(graph_claims(aud=resource.rstrip("/")))
        return (0, json.dumps({"accessToken": token, "expires_on": 4_102_444_800}), "")
    if args[:2] == ["account", "show"]:
        return (0, json.dumps(account_json(SUBSCRIPTION, TENANT, default=True)), "")
    raise AssertionError(args)


def arm_item(role: str, ends: str | None, assignment_type: str = "", status: str = ""):
    return {
        "id": f"/x/{role}/{ends}",
        "properties": {
            "principalId": ME,
            "memberType": "Direct",
            "assignmentType": assignment_type,
            "status": status,
            "requestType": "SelfActivate",
            "justification": "deploy 12",
            "endDateTime": ends,
            "expandedProperties": {
                "roleDefinition": {"displayName": role},
                "scope": {"displayName": "libre-devops-dev"},
            },
        },
    }


class Tenant:
    def __init__(self) -> None:
        self.fail: dict[str, tuple[int, dict]] = {}
        self.requests: list = []

    def __call__(self, request):
        self.requests.append(request)
        url = unquote(request.url)
        parts = urlsplit(request.url)
        path = unquote(parts.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        for fragment, reply in self.fail.items():
            if fragment in url:
                return reply
        if parts.netloc == "management.azure.com":
            if path == "/subscriptions":
                return (200, {"value": [{"subscriptionId": SUBSCRIPTION, "tenantId": TENANT}]})
            if path.endswith("/roleEligibilityScheduleInstances"):
                return (200, {"value": [arm_item("Owner", "2027-01-01T00:00:00Z")]})
            if path.endswith("/roleAssignmentScheduleInstances"):
                return (
                    200,
                    {
                        "value": [
                            arm_item("Reader", None, "Assigned"),
                            arm_item("Owner", "2026-09-24T20:00:00Z", "Activated"),
                        ]
                    },
                )
            if path.endswith("/roleAssignmentScheduleRequests"):
                return (
                    200,
                    {
                        "value": [
                            arm_item("Owner", None, status="PendingApproval"),
                            arm_item("Reader", None, status="Provisioned"),
                        ]
                    },
                )
            if path.endswith("/roleDefinitions"):
                return (
                    200,
                    {"value": [{"id": "/providers/Microsoft.Authorization/roleDefinitions/o"}]},
                )
            if path.endswith("/roleManagementPolicyAssignments"):
                return (200, {"value": [{"properties": {"effectiveRules": RULES}}]})
        if parts.netloc == "graph.microsoft.com":
            if path == "/v1.0/users/ana@example.com":
                return (
                    200,
                    {"id": ME, "displayName": "Ana", "userPrincipalName": "ana@example.com"},
                )
            if path.endswith("/roleDefinitions"):
                return (200, {"value": [{"id": ROLE, "displayName": "Global Administrator"}]})
            if path == "/v1.0/groups" and "displayName" in query.get("$filter", ""):
                return (200, {"value": [{"id": GROUP, "displayName": "Platform Admins"}]})
            if path == f"/v1.0/groups/{GROUP}":
                return (200, {"displayName": "Platform Admins"})
            if "privilegedAccess/group" in path:
                return (200, {"value": [{"accessId": "member", "groupId": GROUP}]})
            if "roleManagement/directory" in path:
                return (200, {"value": [{"roleDefinitionId": ROLE, "directoryScopeId": "/"}]})
            if path == "/v1.0/policies/roleManagementPolicyAssignments":
                return (200, {"value": [{"policy": {"rules": RULES}}]})
        raise AssertionError(f"unexpected {url}")


@pytest.fixture
def tenant():
    return Tenant()


def invoke(tmp_path, tenant, args):
    config = tmp_path / "config.toml"
    config.write_text(CONFIG, encoding="utf-8")
    obj = Runtime(
        config_path=config, az_runner=az_runner(az_responder)[0], session=fake_session(tenant)[0]
    )
    return runner.invoke(app, args, obj=obj)


def test_one_area_failing_is_a_warning_and_the_others_still_show(tmp_path, tenant):
    tenant.fail["roleManagement/directory/roleEligibility"] = NO_SCOPE
    result = invoke(tmp_path, tenant, ["pim", "eligible", "-o", "json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert {(row["area"], row["role"]) for row in rows} == {
        ("azure", "Owner"),
        ("groups", "member"),
    }
    assert "warning: entra:" in result.stderr
    assert 'auth = "interactive"' in result.stderr


def test_every_asked_area_failing_is_an_error(tmp_path, tenant):
    tenant.fail["roleEligibilityScheduleInstances"] = NO_LICENCE
    result = invoke(tmp_path, tenant, ["pim", "eligible", "--azure"])
    assert result.exit_code == 1
    assert "Entra ID P2" in result.stderr


def test_permanent_only_shows_standing_access(tmp_path, tenant):
    result = invoke(tmp_path, tenant, ["pim", "active", "--azure", "--permanent-only", "-o", "csv"])
    assert result.exit_code == 0, result.output
    header, *rows = result.stdout.splitlines()
    assert header == "AREA,ROLE,SCOPE,MEMBERSHIP,TYPE,FROM,UNTIL"
    assert rows == ["azure,Reader,libre-devops-dev,Direct,Assigned,-,permanent"]


def test_a_named_user_is_resolved_then_searched_per_subscription(tmp_path, tenant):
    result = invoke(tmp_path, tenant, ["pim", "eligible", "--azure", "--user", "ana@example.com"])
    assert result.exit_code == 0, result.output
    arm = next(r for r in tenant.requests if "roleEligibilityScheduleInstances" in r.url)
    assert urlsplit(arm.url).path.startswith(f"/subscriptions/{SUBSCRIPTION}/")
    assert parse_qs(urlsplit(arm.url).query)["$filter"] == [f"assignedTo('{ME}')"]


def test_approvals_show_only_what_is_still_waiting(tmp_path, tenant):
    result = invoke(tmp_path, tenant, ["pim", "approvals", "--azure", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert [row["status"] for row in json.loads(result.stdout)] == ["PendingApproval"]
    arm = next(r for r in tenant.requests if "roleAssignmentScheduleRequests" in r.url)
    assert parse_qs(urlsplit(arm.url).query)["$filter"] == ["asApprover()"]


@pytest.mark.parametrize(
    ("args", "area"),
    [
        (["pim", "settings", "Global Administrator"], "entra"),
        (["pim", "settings", "Owner", "--scope", f"/subscriptions/{SUBSCRIPTION}"], "azure"),
        (["pim", "settings", "--group", "Platform Admins"], "groups"),
    ],
)
def test_settings_for_each_area(tmp_path, tenant, args, area):
    result = invoke(tmp_path, tenant, args)
    assert result.exit_code == 0, result.output
    assert f"Area                    {area}" in result.stdout
    assert "Longest activation      8h" in result.stdout
    assert "Needs MFA               yes" in result.stdout


def test_settings_explain_a_missing_scope(tmp_path, tenant):
    tenant.fail["roleManagementPolicyAssignments"] = NO_SCOPE
    result = invoke(tmp_path, tenant, ["pim", "settings", "Global Administrator"])
    assert result.exit_code == 1
    assert 'auth = "interactive"' in (result.exception.hint or "")
