import json

from fakes.http import routes
from fakes.tenant import invoke, run, runner, runtime
from libre_devops_helpers.cli import app

GROUP_ID = "55555555-5555-5555-5555-555555555555"
USER_ID = "88888888-8888-8888-8888-888888888888"
DEVICE_ID = "66666666-6666-6666-6666-666666666666"
STALE_ID = "67676767-6767-6767-6767-676767676767"
GROUPS = "/v1.0/groups"
ANA = (200, {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"})


def device(object_id: str = DEVICE_ID) -> dict:
    return {
        "id": object_id,
        "displayName": "web01",
        "operatingSystem": "Linux",
        "operatingSystemVersion": "9.4",
        "accountEnabled": True,
        "trustType": "ServerAd",
    }


def group(name: str = "Ring 1", *, dynamic: bool = False) -> dict:
    return {
        "id": GROUP_ID,
        "displayName": name,
        "groupTypes": ["DynamicMembership"] if dynamic else [],
        "securityEnabled": True,
    }


def test_app_credentials_exits_3_when_one_is_expiring(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "app-credentials", "-o", "csv"])
    assert result.exit_code == 3, result.output
    header, row = result.stdout.splitlines()
    assert header.startswith("APP,KIND,CREDENTIAL")
    assert row.startswith("billing-api,secret,ci,")


def test_an_empty_ca_policy_list_warns_that_the_token_may_be_why(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "ca-policies"])
    assert result.exit_code == 0, result.output
    assert "may lack Policy.Read.All" in result.stderr


def test_device_groups_reports_a_missing_device(profiles_config):
    result = runner.invoke(
        app,
        ["entra", "device-groups", "ghost.corp.example.com"],
        obj=runtime(profiles_config, lambda request: (200, {"value": []})),
    )
    assert result.exit_code == 1
    assert "no Entra device is named 'ghost.corp.example.com' or 'ghost'" in str(result.exception)


def test_device_groups_warns_about_stale_registrations_with_the_same_name(config_file):
    memberships = (200, {"value": [group("Linux servers", dynamic=True)]})
    handler = routes(
        {
            "/v1.0/devices": (200, {"value": [device(), device(STALE_ID)]}),
            f"/v1.0/devices/{DEVICE_ID}/transitiveMemberOf/microsoft.graph.group": memberships,
            f"/v1.0/devices/{STALE_ID}/transitiveMemberOf/microsoft.graph.group": (
                200,
                {"value": []},
            ),
        }
    )
    result = run(config_file, handler, ["entra", "device-groups", "web01"])
    assert result.exit_code == 0, result.output
    assert "2 Entra devices are named 'web01'" in result.stderr
    assert "Linux servers" in result.stdout
    assert "(no group memberships)" in result.stdout
    records = json.loads(
        run(config_file, handler, ["entra", "device-groups", "web01", "-o", "json"]).stdout
    )
    assert [len(record["groups"]) for record in records] == [1, 0]


def test_group_devices_names_the_group_and_its_membership_type(config_file):
    handler = routes(
        {
            GROUPS: (200, {"value": [group(dynamic=True)]}),
            f"{GROUPS}/{GROUP_ID}/members/microsoft.graph.device": (200, {"value": [device()]}),
        }
    )
    result = run(config_file, handler, ["entra", "group-devices", "Ring 1", "--direct"])
    assert result.exit_code == 0, result.output
    assert f"Ring 1  object {GROUP_ID}  dynamic  1 device(s)" in result.stdout
    assert "ServerAd" in result.stdout


def test_group_members_of_one_kind(config_file):
    member = {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"}
    handler = routes(
        {
            GROUPS: (200, {"value": [group()]}),
            f"{GROUPS}/{GROUP_ID}/transitiveMembers/microsoft.graph.user": (
                200,
                {"value": [member]},
            ),
        }
    )
    result = run(config_file, handler, ["entra", "group-members", "Ring 1", "--kind", "USER"])
    assert result.exit_code == 0, result.output
    assert "Ring 1  1 member(s)" in result.stdout
    assert "ana@example.com" in result.stdout


def test_group_members_rejects_an_unknown_kind(config_file):
    result = run(config_file, routes({}), ["entra", "group-members", "Ring 1", "--kind", "robot"])
    assert result.exit_code == 2
    assert "--kind must be one of" in result.output


def test_user_groups_for_a_upn(config_file):
    handler = routes(
        {
            "/v1.0/users/ana@example.com": ANA,
            f"/v1.0/users/{USER_ID}/transitiveMemberOf/microsoft.graph.group": (
                200,
                {"value": [group("Admins")]},
            ),
        }
    )
    result = run(config_file, handler, ["entra", "user-groups", "ana@example.com"])
    assert result.exit_code == 0, result.output
    assert f"ana@example.com  object {USER_ID}  1 group(s)" in result.stdout
    assert "Admins" in result.stdout


def test_user_roles_shows_active_roles_and_warns_when_eligibility_is_unreadable(config_file):
    handler = routes(
        {
            "/v1.0/users/ana@example.com": ANA,
            f"/v1.0/users/{USER_ID}/transitiveMemberOf/microsoft.graph.directoryRole": (
                200,
                {"value": [{"id": "r1", "displayName": "Global Reader", "roleTemplateId": "t1"}]},
            ),
            "/v1.0/roleManagement/directory/roleEligibilitySchedules": (
                403,
                {"error": {"code": "Forbidden", "message": "needs P2"}},
            ),
        }
    )
    result = run(config_file, handler, ["entra", "user-roles", "ana@example.com"])
    assert result.exit_code == 0, result.output
    assert "Global Reader" in result.stdout
    assert "permanent" in result.stdout
    assert "PIM eligibility could not be read" in result.stderr
    assert "needs P2" in result.stderr


def test_sign_ins_show_failures_and_count_them(config_file):
    event = {
        "id": "1",
        "createdDateTime": "2026-09-24T08:00:00Z",
        "userPrincipalName": "ana@example.com",
        "appDisplayName": "Azure Portal",
        "status": {"errorCode": 50126, "failureReason": "Invalid password"},
    }
    handler = routes({"/v1.0/auditLogs/signIns": (200, {"value": [event]})})
    result = run(config_file, handler, ["entra", "sign-ins", "--failures", "--since", "2h"])
    assert result.exit_code == 0, result.output
    assert "50126 Invalid password" in result.stdout
    assert "1 sign-in(s) in the last 2h" in result.stderr
