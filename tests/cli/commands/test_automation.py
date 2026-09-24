import json

from fakes.automation import ACCOUNT_ID, FakeAutomation, account
from fakes.ids import OTHER_SUBSCRIPTION
from fakes.tenant import run
from libre_devops_helpers.core.errors import AmbiguousError, InputError


def automation(config_file, args, fake=None):
    fake = fake or FakeAutomation()
    return run(config_file, fake.handler, ["azure", "automation", *args]), fake


def test_accounts_are_listed_across_the_tenants_subscriptions(config_file):
    result, _ = automation(config_file, ["accounts", "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[1].startswith("aa-ops,rg-ops,uksouth,")


def test_jobs_are_newest_first_and_a_failure_exits_3(config_file):
    result, _ = automation(config_file, ["jobs", "aa-ops", "-o", "csv"])
    assert result.exit_code == 3, result.output
    rows = [line.split(",")[:3] for line in result.stdout.splitlines()[1:]]
    assert rows == [
        ["job-3", "Rotate-Keys", "Failed"],
        ["job-2", "Patch-Servers", "Completed"],
        ["job-1", "Rotate-Keys", "Completed"],
    ]
    assert "3 job(s) in aa-ops, 1 failed" in result.stderr


def test_jobs_filter_by_runbook_status_and_window(config_file):
    one, _ = automation(config_file, ["jobs", "aa-ops", "--runbook", "patch-servers", "-o", "csv"])
    assert one.exit_code == 0, one.output
    assert [line.split(",")[0] for line in one.stdout.splitlines()[1:]] == ["job-2"]
    failed, _ = automation(config_file, ["jobs", "aa-ops", "--failed", "-o", "csv"])
    assert [line.split(",")[0] for line in failed.stdout.splitlines()[1:]] == ["job-3"]
    recent, _ = automation(
        config_file, ["jobs", "aa-ops", "--since", "24h", "--status", "completed", "-o", "csv"]
    )
    assert [line.split(",")[0] for line in recent.stdout.splitlines()[1:]] == ["job-2"]


def test_logs_default_to_the_newest_job_and_show_why_it_failed(config_file):
    result, _ = automation(config_file, ["logs", "aa-ops"])
    assert result.exit_code == 3, result.output
    assert "Rotate-Keys" in result.stdout
    assert "Key Vault kv-app-prd refused the request" in result.stdout
    assert "Schedule: nightly" in result.stdout
    streams = [line.split()[-1] for line in result.stdout.splitlines() if "Retrying" in line]
    assert streams == ["kv-app-prd"]
    order = [word for word in result.stdout.split() if word in {"Output", "Warning", "Error"}]
    assert order == ["Output", "Warning", "Error"]


def test_logs_for_a_runbook_and_one_stream_in_full(config_file):
    ok, _ = automation(config_file, ["logs", "aa-ops", "--runbook", "Patch-Servers"])
    assert ok.exit_code == 0, ok.output
    assert "Patched 12 servers" in ok.stdout
    result, fake = automation(
        config_file, ["logs", "aa-ops", "job-3", "--stream", "error", "--full", "-o", "json"]
    )
    record = json.loads(result.stdout)
    assert record["job"]["name"] == "job-3"
    assert [item["message"] for item in record["streams"]] == [
        "Forbidden: the caller has no get permission on secrets in kv-app-prd"
    ]
    assert any(url.split("?")[0].endswith("/streams/s2") for url in fake.requests)


def test_an_unknown_stream_is_refused_before_anything_is_read(config_file):
    result, fake = automation(config_file, ["logs", "aa-ops", "--stream", "chatter"])
    assert isinstance(result.exception, InputError)
    assert fake.requests == []


def test_output_is_the_newest_jobs_text_for_piping(config_file):
    result, _ = automation(config_file, ["output", "aa-ops", "--runbook", "Rotate-Keys"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "Rotating 3 keys\n"
    assert "job job-3 in aa-ops" in result.stderr


def test_an_account_by_resource_id_needs_no_subscription_search(config_file):
    result, fake = automation(config_file, ["jobs", ACCOUNT_ID, "--runbook", "Patch-Servers"])
    assert result.exit_code == 0, result.output
    assert not any(url.split("?")[0].endswith("/subscriptions") for url in fake.requests)


def test_a_shared_account_name_asks_for_the_resource_group(config_file):
    fake = FakeAutomation()
    fake.accounts[OTHER_SUBSCRIPTION] = [account(group="rg-dev", subscription=OTHER_SUBSCRIPTION)]
    result, _ = automation(config_file, ["jobs", "aa-ops"], fake)
    assert isinstance(result.exception, AmbiguousError)
    narrowed, _ = automation(config_file, ["jobs", "aa-ops", "-g", "rg-ops", "-n", "1"], fake)
    assert narrowed.exit_code == 3, narrowed.output  # job-3, the newest, failed
