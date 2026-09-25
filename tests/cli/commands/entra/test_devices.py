import json
from urllib.parse import unquote

from fakes.entra import DEVICE_ID, GROUP_ID, GROUPS, STALE_ID, device, group
from fakes.http import routes
from fakes.tenant import run, runner, runtime
from libre_devops_helpers.cli import app


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


def entra_devices(request):
    """web01 is in Entra (found by its short name); anything else is not."""
    return (200, {"value": [device()] if "'web01'" in unquote(request.url) else []})


def membership(*members: dict):
    seen = []

    def handler(request):
        seen.append(unquote(request.url))
        return (200, {"value": list(members)})

    return handler, seen


def test_entra_devices_checks_a_group_named_by_its_display_name(config_file):
    members, _ = membership(device())
    handler = routes(
        {
            "/v1.0/devices": entra_devices,
            GROUPS: (200, {"value": [group("MDE Pilot Devices")]}),
            f"{GROUPS}/{GROUP_ID}/transitiveMembers/microsoft.graph.device": members,
        }
    )
    args = ["entra", "devices", "web01.corp.example.com,db01", "--group", "MDE Pilot Devices"]
    result = run(config_file, handler, [*args, "-o", "json"])
    assert result.exit_code == 3, result.output  # db01 is not in Entra
    web01, db01 = json.loads(result.stdout)
    assert web01["groups"] == [{"id": GROUP_ID, "name": "MDE Pilot Devices", "member": True}]
    assert (db01["found"], db01["groups"][0]["member"]) == (False, False)
    assert "1 of 2 in Entra, 1 in every group" in result.stderr
    table = run(config_file, handler, args)
    assert "IN MDE Pilot Devices" in table.stdout.splitlines()[0]


def test_entra_devices_takes_a_group_object_id_and_direct_membership(config_file):
    members, seen = membership()  # web01 is not a direct member
    handler = routes(
        {
            "/v1.0/devices": entra_devices,
            f"{GROUPS}/{GROUP_ID}": (200, group("Ring 1")),
            f"{GROUPS}/{GROUP_ID}/members/microsoft.graph.device": members,
        }
    )
    args = ["entra", "devices", "web01", "--group", GROUP_ID, "--direct", "-o", "csv"]
    result = run(config_file, handler, args)
    assert result.exit_code == 3, result.output
    header, row = result.stdout.splitlines()
    assert header.endswith(",IN Ring 1")
    assert row.startswith("web01,web01,Linux 9.4,yes,ServerAd,")
    assert row.endswith(",no")
    assert seen
    assert all("/members/" in url for url in seen)


def test_entra_devices_without_a_group_just_looks_them_up(config_file):
    handler = routes({"/v1.0/devices": entra_devices})
    result = run(config_file, handler, ["entra", "devices", "web01"])
    assert result.exit_code == 0, result.output
    assert "1 of 1 in Entra" in result.stderr
