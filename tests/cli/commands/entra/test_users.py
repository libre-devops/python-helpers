from fakes.entra import ANA, USER_ID, group
from fakes.http import routes
from fakes.tenant import run


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
    assert "1 sign-in(s) in the last 2h" in result.stderr.splitlines()
