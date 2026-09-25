import json
from urllib.parse import unquote

from fakes.http import routes
from fakes.tenant import run, runner, runtime
from fakes.xdr import MACHINES, ago, by_name, machine
from libre_devops_helpers.cli import app


def test_check_devices_splits_names_and_exits_3_when_one_is_missing(profiles_config):
    record = {
        "id": "a" * 40,
        "computerDnsName": "web01",
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": "2026-09-20T00:00:00Z",
    }

    def handler(request):
        found = "'web01'" in unquote(request.url)
        return (200, {"value": [record] if found else []})

    result = runner.invoke(
        app, ["xdr", "machines", "web01,ghost", "-o", "json"], obj=runtime(profiles_config, handler)
    )
    assert result.exit_code == 3, result.output
    lookups = json.loads(result.stdout)
    assert [(item["query"], item["found"]) for item in lookups] == [
        ("web01", True),
        ("ghost", False),
    ]


def test_machines_table_shows_health_tags_and_older_records(config_file):
    older = machine(last_seen=ago(40), id="b" * 40, healthStatus="Inactive")
    handler = routes({MACHINES: (200, {"value": [machine(), older]})})
    result = run(config_file, handler, ["xdr", "machines", "web01"])
    assert result.exit_code == 0, result.output
    assert "linux-servers" in result.stdout
    assert "DEVICE GROUP" in result.stdout
    assert "Linux servers" in result.stdout
    assert "older record" not in result.stdout
    everything = run(config_file, handler, ["xdr", "machines", "web01", "--all-records"])
    assert "older record" in everything.stdout
    assert "Inactive" in everything.stdout


def test_stale_lists_silent_machines_and_exits_3(config_file):
    handler = routes({MACHINES: (200, {"value": [machine("old01", ago(45))]})})
    result = run(config_file, handler, ["xdr", "stale", "--older-than", "30d"])
    assert result.exit_code == 3, result.output
    assert "old01" in result.stdout
    assert "1 machine(s) not seen for 30d" in result.stderr
    quiet = run(config_file, routes({MACHINES: (200, {"value": []})}), ["xdr", "stale"])
    assert quiet.exit_code == 0


def test_machines_found_by_a_short_name_say_so(config_file):
    def prefixed(request):
        text = unquote(request.url)
        found = "startswith(computerDnsName,'app07.')" in text
        return (200, {"value": [machine("app07.corp.example")] if found else []})

    result = run(
        config_file, routes({MACHINES: prefixed}), ["xdr", "machines", "app07", "-o", "csv"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[1].startswith("app07,prefix,")


def test_machines_as_tsv_cut_like_a_shell_would(config_file):
    result = run(
        config_file, routes({MACHINES: by_name}), ["xdr", "machines", "web01", "-o", "tsv"]
    )
    assert result.exit_code == 0, result.output
    (line,) = result.stdout.splitlines()  # no header
    fields = line.split("\t")
    assert (fields[0], fields[1], fields[2]) == ("web01", "fqdn", "Onboarded")
