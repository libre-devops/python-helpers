import json

from fakes.clock import FakeClock
from fakes.http import routes
from fakes.tenant import invoke, run
from fakes.workbooks import write_workbook
from libre_devops_helpers.core.errors import InputError


def test_devices_check_exits_3_and_says_which_device_is_short(config_file, tenant):
    result = invoke(config_file, tenant, ["devices", "check", "web01,web02", "-o", "json"])
    assert result.exit_code == 3, result.output
    report = json.loads(result.stdout)
    assert not report["complete"]
    by_name = {device["name"]: device for device in report["devices"]}
    assert by_name["web01"]["complete"]
    assert by_name["web02"]["checks"]["defender"]["detail"] == "no Defender record"


def test_devices_check_reads_names_from_a_csv_column(config_file, tenant, tmp_path):
    hosts = tmp_path / "plan.csv"
    hosts.write_text("FQDN,Ring\nweb01,1\n", encoding="utf-8")
    result = invoke(
        config_file, tenant, ["devices", "check", "-f", str(hosts), "--column", "fqdn", "-o", "csv"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["DEVICE,ENTRA,DEFENDER", "web01,ok,ok"]


def test_devices_check_reads_names_from_an_excel_sheet(config_file, tenant, tmp_path):
    plan = write_workbook(
        tmp_path / "plan.xlsm",
        {
            "Ring 1": [["Ring 1"], ["Host", "FQDN"], ["web01", "web01"]],
            "Ring 2": [["Host", "FQDN"], ["web02", "web02"]],
        },
    )
    command = ["devices", "check", "-f", str(plan), "--column", "FQDN", "-o", "csv"]
    result = invoke(config_file, tenant, [*command, "--sheet", "ring 1"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["DEVICE,ENTRA,DEFENDER", "web01,ok,ok"]
    # Both sheets have the column, so without --sheet it asks which.
    result = invoke(config_file, tenant, command)
    assert isinstance(result.exception, InputError)
    assert result.exception.hint == "pick one with --sheet (Ring 1, Ring 2)"


def test_devices_watch_waits_on_the_fake_clock_until_complete(config_file, tenant):
    clock = FakeClock()

    def arrive_after_ten_minutes():
        if clock.now >= 600:
            tenant.devices.add("web02")
            tenant.machines.add("web02")

    tenant.before = arrive_after_ten_minutes
    result = invoke(
        config_file,
        tenant,
        ["devices", "watch", "web01", "web02", "--interval", "5m", "--timeout", "1h"],
        clock=clock,
    )
    assert result.exit_code == 0, result.output
    assert clock.sleeps == [300, 300]
    assert "pass 1: 1/2 complete" in result.stderr
    assert "every device meets every expectation after 3 pass(es)" in result.stderr


def test_devices_watch_exits_3_when_the_limit_is_reached(config_file, tenant):
    clock = FakeClock()
    result = invoke(
        config_file,
        tenant,
        ["devices", "watch", "ghost", "--interval", "1m", "--max-passes", "2"],
        clock=clock,
    )
    assert result.exit_code == 3, result.output
    assert "reached --max-passes" in result.stderr
    assert clock.sleeps == [60]


def test_devices_watch_rejects_a_bad_interval(config_file, tenant):
    result = invoke(config_file, tenant, ["devices", "watch", "web01", "--interval", "soon"])
    assert result.exit_code == 2


def test_devices_show_passes_a_healthy_device_and_flags_a_missing_one(config_file, tenant):
    healthy = invoke(config_file, tenant, ["devices", "show", "web01"])
    assert healthy.exit_code == 0, healthy.output
    assert "nothing looks wrong" in healthy.stdout
    tenant.devices.add("web02")
    missing = invoke(config_file, tenant, ["devices", "show", "web02", "-o", "json"])
    assert missing.exit_code == 3, missing.output
    findings = json.loads(missing.stdout)["findings"]
    assert {"level": "warn", "message": "no Defender record"} in findings


AV_REPLY = {
    "schema": [{"name": "DeviceName"}, {"name": "AvSignatureVersion"}],
    "results": [
        {
            "DeviceId": "m1",
            "DeviceName": "web01.corp.example.com",
            "OSPlatform": "Windows11",
            "Reported": "2026-09-24T08:00:00Z",
            "AvSignatureVersion": "1.419.120.0",
            "AvEngineVersion": "1.1.24080.9",
            "AvPlatformVersion": "4.18.24080.9",
            "AvMode": "0",
            "SignatureUpToDate": True,
        }
    ],
}


def test_av_signature_goes_through_graph_hunting(config_file):
    seen = []

    def hunting(request):
        seen.append(json.loads(request.body))
        return (200, AV_REPLY)

    handler = routes({"/v1.0/security/runHuntingQuery": hunting})
    result = run(config_file, handler, ["device", "av-signature", "web01", "-o", "csv"])
    assert result.exit_code == 0, result.output
    header, line = result.stdout.splitlines()
    assert header == "DEVICE,MACHINE,OS,SIGNATURE,ENGINE,PLATFORM,MODE,UP TO DATE,REPORTED"
    assert line.startswith(
        "web01,web01.corp.example.com,Windows11,1.419.120.0,1.1.24080.9,4.18.24080.9,active,yes,"
    )
    assert "DeviceTvmInfoGathering" in seen[0]["Query"]
    assert "Timespan" not in seen[0]
    assert "1 found" in result.stderr


def test_av_signature_exits_3_for_a_missing_or_old_device(config_file):
    handler = routes({"/v1.0/security/runHuntingQuery": (200, AV_REPLY)})
    args = ["devices", "av-signature", "web01,ghost", "--at-least", "1.419.200.0", "-o", "json"]
    result = run(config_file, handler, args)
    assert result.exit_code == 3, result.output
    web01, ghost = json.loads(result.stdout)
    assert (web01["signature_version"], web01["older_than_minimum"]) == ("1.419.120.0", True)
    assert (ghost["found"], ghost["older_than_minimum"]) == (False, None)
    assert "1 not found, 1 older than 1.419.200.0" in result.stderr


def test_av_signature_with_endpoint_uses_the_defender_api(config_file):
    endpoint = {"Schema": AV_REPLY["schema"], "Results": AV_REPLY["results"]}
    handler = routes({"/api/advancedqueries/run": (200, endpoint)})
    result = run(config_file, handler, ["devices", "av-signature", "web01", "--endpoint"])
    assert result.exit_code == 0, result.output
    assert "1.419.120.0" in result.stdout


def test_av_signature_can_print_its_query_or_refuse_a_bad_version(config_file):
    shown = run(config_file, routes({}), ["devices", "av-signature", "web01", "--show-query"])
    assert shown.exit_code == 0, shown.output
    assert shown.stdout.startswith('let wanted = dynamic(["web01"]);')
    bad = run(config_file, routes({}), ["devices", "av-signature", "web01", "--at-least", "new"])
    assert isinstance(bad.exception, InputError)
