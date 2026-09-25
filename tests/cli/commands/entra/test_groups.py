from fakes.entra import GROUP_ID, GROUPS, USER_ID, device, group
from fakes.http import routes
from fakes.tenant import run, usage_error


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
    assert "--kind must be one of" in usage_error(result)
