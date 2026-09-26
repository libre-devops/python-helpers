import json

from fakes.clock import FakeClock
from fakes.tenant import invoke
from fakes.workbooks import Styled, write_workbook
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
    assert result.stdout.splitlines() == ["DEVICE,MET,ENTRA,DEFENDER", "web01,2/2,ok,ok"]


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
    assert result.stdout.splitlines() == ["DEVICE,MET,ENTRA,DEFENDER", "web01,2/2,ok,ok"]
    # Both sheets have the column, so without --sheet it asks which.
    result = invoke(config_file, tenant, command)
    assert isinstance(result.exception, InputError)
    assert result.exception.hint == "pick one with --sheet (Ring 1, Ring 2)"


def test_the_complete_devices_sort_first_by_how_many_checks_they_meet(config_file, tenant):
    args = ["devices", "check", "ghost,web01,phantom", "--sort", "met:desc", "-o", "csv"]
    result = invoke(config_file, tenant, args)
    assert result.exit_code == 3, result.output
    rows = [line.split(",")[:2] for line in result.stdout.splitlines()[1:]]
    assert rows == [["web01", "2/2"], ["ghost", "0/2"], ["phantom", "0/2"]]  # ties keep their order
    plain = invoke(config_file, tenant, ["devices", "check", "ghost,web01", "-o", "csv"])
    assert [line.split(",")[0] for line in plain.stdout.splitlines()[1:]] == ["ghost", "web01"]


def test_devices_check_takes_a_defender_device_group(config_file, tenant):
    args = ["devices", "check", "web01", "--device-group", "Linux servers", "-o", "csv"]
    result = invoke(config_file, tenant, args)
    assert result.stdout.splitlines()[0] == "DEVICE,MET,ENTRA,DEFENDER,DEVICE GROUP LINUX SERVERS"


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


def test_devices_watch_takes_the_days_servers_from_a_workbook(config_file, tenant, tmp_path):
    plan = write_workbook(
        tmp_path / "plan.xlsx",
        {
            "Plan": [
                ["Server", "Scheduled Date", "Status"],
                ["web01", Styled(46290, "dd/mm/yyyy"), ""],
                ["web02", Styled(46291, "dd/mm/yyyy"), ""],
                ["db01", Styled(46290, "dd/mm/yyyy"), "Done"],
            ]
        },
    )
    args = ["devices", "watch", "-f", str(plan), "--column", "Server"]
    args += ["--where", "Scheduled Date=2026-09-25", "--where", "Status!=Done", "--max-passes", "1"]
    result = invoke(config_file, tenant, args, clock=FakeClock())
    assert result.exit_code == 0, result.output
    assert (
        "1 name(s) from the rows where Scheduled Date=2026-09-25 and Status!=Done" in result.stderr
    )
    looked_up = {
        r.url for r in tenant.requests if "/v1.0/devices" in r.url or "/api/machines" in r.url
    }
    assert looked_up
    assert all("web01" in url for url in looked_up)
    assert "every device meets every expectation after 1 pass(es)" in result.stderr


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
