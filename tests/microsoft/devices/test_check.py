import threading
from datetime import timedelta

import pytest

from fakes.clock import FakeClock
from fakes.devices import GROUP_ID, NOW, FakeTenant, clients, intune_client
from libre_devops_helpers.core.auth import AccessToken
from libre_devops_helpers.core.errors import ApiError, InputError, ReauthRequired
from libre_devops_helpers.core.poll import PollLimits
from libre_devops_helpers.microsoft.devices import (
    DeviceChecker,
    Expectations,
    watch,
)


def checker(tenant: FakeTenant, **options) -> DeviceChecker:
    entra, xdr = clients(tenant)
    return DeviceChecker(entra=entra, xdr=xdr, clock=lambda: NOW, **options)


def statuses(run, name: str) -> dict[str, str]:
    report = next(report for report in run.reports if report.name == name)
    return {outcome.check: outcome.status for outcome in report.outcomes}


def test_default_expectations_are_entra_and_defender():
    tenant = FakeTenant()
    tenant.add("web01")
    run = checker(tenant).check(["web01"], Expectations())
    assert run.complete
    assert statuses(run, "web01") == {"entra": "met", "defender": "met"}


def test_unmet_expectations_say_why():
    tenant = FakeTenant()
    tenant.add("web01", onboarded=False)
    run = checker(tenant).check(["web01", "ghost"], Expectations(active=True))
    assert not run.complete
    web01 = next(report for report in run.reports if report.name == "web01")
    assert web01.outcome("defender").detail == "CanBeOnboarded"
    assert statuses(run, "ghost") == {"entra": "unmet", "defender": "unmet", "active": "unmet"}
    assert run.counts(Expectations(active=True).checks) == {"entra": 1, "defender": 0, "active": 1}


def test_tags_and_groups_with_group_members_fetched_once_per_pass():
    tenant = FakeTenant()
    for name in ("web01", "web02", "web03"):
        tenant.add(name, tags=["linux-servers"] if name != "web03" else [])
    tenant.group_members = ["web01", "web03"]
    expectations = Expectations(tags=("Linux-Servers",), groups=("Pilot",))
    run = checker(tenant).check(["web01", "web02", "web03"], expectations)
    assert statuses(run, "web01") == {
        "entra": "met",
        "defender": "met",
        "tag Linux-Servers": "met",
        "group Pilot": "met",
    }
    assert statuses(run, "web02")["group Pilot"] == "unmet"
    assert statuses(run, "web03")["tag Linux-Servers"] == "unmet"
    assert sum("transitiveMembers" in url for url in tenant.calls) == 1


def test_results_keep_the_input_order_with_parallel_lookups():
    tenant = FakeTenant()
    names = [f"host{n:02d}" for n in range(20)]
    for name in names:
        tenant.add(name)
    run = checker(tenant, workers=8).check(names, Expectations())
    assert [report.name for report in run.reports] == names


def test_a_failed_lookup_is_an_error_for_that_device_only():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.add("web02")
    tenant.fail["'web02'"] = (400, {"error": {"code": "BadRequest", "message": "bad filter"}})
    run = checker(tenant).check(["web01", "web02"], Expectations())
    assert statuses(run, "web01") == {"entra": "met", "defender": "met"}
    assert statuses(run, "web02") == {"entra": "error", "defender": "error"}


def test_a_rejected_token_ends_the_check():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.fail["/api/machines"] = (403, {"error": {"code": "Forbidden", "message": "no role"}})
    with pytest.raises(ApiError) as caught:
        checker(tenant).check(["web01"], Expectations())
    assert caught.value.status == 403


def test_only_the_services_the_expectations_need_are_called():
    tenant = FakeTenant()
    tenant.add("web01")
    entra, _ = clients(tenant)
    run = DeviceChecker(entra=entra).check(["web01"], Expectations(onboarded=False))
    assert run.complete
    assert not any("/api/machines" in url for url in tenant.calls)
    # A caller's mistake, not a person's: a plain ValueError, as for any bad argument.
    with pytest.raises(ValueError, match="Defender"):
        DeviceChecker(entra=entra).check(["web01"], Expectations())


def test_expectations_need_at_least_one_check():
    with pytest.raises(InputError, match="nothing to check"):
        Expectations(in_entra=False, onboarded=False)


def test_watch_completes_when_the_last_device_arrives_and_skips_finished_ones():
    tenant = FakeTenant()
    tenant.add("web01")
    clock = FakeClock()
    passes: list[int] = []

    def on_pass(number, run):
        passes.append(number)
        if number == 2:
            tenant.add("web02")

    outcome = watch(
        checker(tenant),
        ["web01", "web02"],
        Expectations(),
        PollLimits(interval=300, timeout=3600),
        clock=clock,
        sleep=clock.sleep,
        on_pass=on_pass,
    )
    assert outcome.complete
    assert outcome.passes == 3
    assert [report.name for report in outcome.result.reports] == ["web01", "web02"]
    # web01 met everything on pass 1, so passes 2 and 3 only looked at web02.
    assert tenant.defender_calls("web01") == 1
    assert clock.sleeps == [300, 300]


def test_watch_with_recheck_looks_at_every_device_each_pass():
    tenant = FakeTenant()
    tenant.add("web01")
    clock = FakeClock()
    watch(
        checker(tenant),
        ["web01", "ghost"],
        Expectations(),
        PollLimits(interval=60, max_passes=3),
        recheck=True,
        clock=clock,
        sleep=clock.sleep,
    )
    assert tenant.defender_calls("web01") == 3


def test_watch_times_out_on_the_users_limit():
    tenant = FakeTenant()
    clock = FakeClock()
    outcome = watch(
        checker(tenant),
        ["ghost"],
        Expectations(),
        PollLimits(interval=600, timeout=1500),
        clock=clock,
        sleep=clock.sleep,
    )
    assert outcome.reason == "timeout"
    assert not outcome.complete
    assert clock.sleeps == [600, 600, 300]


def test_a_failed_pass_is_reported_and_retried():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.group_members = ["web01"]
    tenant.fail["/v1.0/groups"] = (400, {"error": {"code": "BadRequest", "message": "throttled"}})
    clock = FakeClock()
    runs = []

    def on_pass(number, run):
        runs.append(run)
        tenant.fail.clear()

    outcome = watch(
        checker(tenant),
        ["web01"],
        Expectations(groups=("Pilot",)),
        PollLimits(interval=60, max_passes=3),
        clock=clock,
        sleep=clock.sleep,
        on_pass=on_pass,
    )
    assert runs[0].error is not None
    assert "throttled" in runs[0].error
    assert not runs[0].complete
    assert outcome.passes == 2


def test_a_rejected_token_ends_the_watch():
    tenant = FakeTenant()
    tenant.fail["/v1.0/devices"] = (401, {"error": {"code": "InvalidAuthenticationToken"}})
    clock = FakeClock()
    with pytest.raises(ApiError):
        watch(
            checker(tenant),
            ["web01"],
            Expectations(),
            PollLimits(interval=60),
            clock=clock,
            sleep=clock.sleep,
        )


def test_intune_enrolment_and_compliance_are_checked():
    tenant = FakeTenant()
    for name in ("web01", "web02", "web03"):
        tenant.add(name)
    tenant.enrol("web01")
    tenant.enrol("web02", compliance="noncompliant")
    expectations = Expectations(in_entra=False, onboarded=False, in_intune=True, compliant=True)
    run = checker(tenant, intune=intune_client(tenant)).check(
        ["web01", "web02", "web03"], expectations
    )
    assert statuses(run, "web01") == {"intune": "met", "compliant": "met"}
    assert statuses(run, "web02") == {"intune": "met", "compliant": "unmet"}
    assert statuses(run, "web03") == {"intune": "unmet", "compliant": "unmet"}
    web02 = next(report for report in run.reports if report.name == "web02")
    assert web02.outcome("compliant").detail == "noncompliant"
    assert web02.outcome("intune").detail == "mdm"


def test_an_unreadable_service_is_an_error_for_every_check_that_needs_it():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.fail["/api/machines"] = (400, {"error": {"code": "BadRequest", "message": "down"}})
    tenant.fail["managedDevices"] = (400, {"error": {"code": "BadRequest", "message": "down"}})
    expectations = Expectations(
        active=True, tags=("linux",), groups=("Pilot",), in_intune=True, compliant=True
    )
    run = checker(tenant, intune=intune_client(tenant)).check(["web01"], expectations)
    assert statuses(run, "web01") == {
        "entra": "met",
        "defender": "error",
        "active": "error",
        "tag linux": "error",
        "group Pilot": "unmet",
        "intune": "error",
        "compliant": "error",
    }


def test_active_tags_and_groups_explain_what_is_missing():
    tenant = FakeTenant()
    tenant.add("web01", tags=("windows",))
    tenant.machines["web01"][0]["healthStatus"] = "Inactive"
    expectations = Expectations(active=True, tags=("Linux",), groups=("Pilot",))
    run = checker(tenant).check(["web01", "ghost"], expectations)
    web01 = next(report for report in run.reports if report.name == "web01")
    assert web01.outcome("active").detail == "Inactive"
    assert web01.outcome("tag Linux").detail == "tag missing"
    assert web01.outcome("group Pilot").detail == "not a member"
    ghost = next(report for report in run.reports if report.name == "ghost")
    assert ghost.outcome("tag Linux").detail == "no Defender record"
    assert ghost.outcome("group Pilot").detail == "not in Entra"


class LapsingTokens:
    """Tokens, except that a sign-in lapses: in one worker once, or everywhere (always)."""

    def __init__(self, *, always: bool = False) -> None:
        self.always = always
        self.lapsed_in_worker = False
        self.main_thread_calls = 0

    def get_token(self, resource: str, tenant_id: str) -> AccessToken:
        in_worker = threading.current_thread() is not threading.main_thread()
        if self.always or (in_worker and not self.lapsed_in_worker):
            self.lapsed_in_worker = self.lapsed_in_worker or in_worker
            raise ReauthRequired("the sign-in lapsed", tenant_id=tenant_id, reason="test")
        self.main_thread_calls += not in_worker
        return AccessToken("token", NOW + timedelta(hours=1), tenant_id, resource)


def test_tokens_are_fetched_on_the_calling_thread_before_the_workers_start():
    tenant = FakeTenant()
    tenant.add("web01")
    tokens = LapsingTokens()
    entra, xdr = clients(tenant, tokens)
    tokens.lapsed_in_worker = True  # no lapse at all this time
    run = DeviceChecker(entra=entra, xdr=xdr, clock=lambda: NOW).check(["web01"], Expectations())
    assert run.complete
    assert tokens.main_thread_calls == 2  # one per service: Entra and Defender


def test_a_sign_in_that_lapses_in_a_worker_is_renewed_on_the_calling_thread_and_retried():
    tenant = FakeTenant()
    for name in ("web01", "web02", "web03"):
        tenant.add(name)
    tokens = LapsingTokens()
    entra, xdr = clients(tenant, tokens)
    checker = DeviceChecker(entra=entra, xdr=xdr, clock=lambda: NOW)
    run = checker.check(["web01", "web02", "web03"], Expectations())
    assert tokens.lapsed_in_worker
    assert run.complete
    assert [report.name for report in run.reports] == ["web01", "web02", "web03"]


def test_a_sign_in_nobody_can_renew_ends_the_check():
    tenant = FakeTenant()
    tenant.add("web01")
    entra, xdr = clients(tenant, LapsingTokens(always=True))
    with pytest.raises(ReauthRequired):
        DeviceChecker(entra=entra, xdr=xdr, clock=lambda: NOW).check(["web01"], Expectations())


def test_defender_device_groups_are_read_from_the_machine_record():
    tenant = FakeTenant()
    tenant.add("web01", device_group="Linux servers")
    tenant.add("web02")
    expectations = Expectations(in_entra=False, device_groups=("linux SERVERS",))
    run = checker(tenant).check(["web01", "web02", "ghost"], expectations)
    reports = {report.name: report for report in run.reports}
    check = "device group linux SERVERS"
    assert reports["web01"].outcome(check).status == "met"
    assert reports["web02"].outcome(check).detail == "in UnassignedGroup"
    assert reports["ghost"].outcome(check).detail == "no Defender record"
    assert not any("/v1.0/" in url for url in tenant.calls)  # Defender only


def test_an_entra_group_can_be_named_by_its_object_id():
    tenant = FakeTenant()
    for name in ("web01", "web02"):
        tenant.add(name)
    tenant.group_members = ["web01"]
    run = checker(tenant).check(["web01", "web02"], Expectations(groups=(GROUP_ID,)))
    assert statuses(run, "web01")[f"group {GROUP_ID}"] == "met"
    assert statuses(run, "web02")[f"group {GROUP_ID}"] == "unmet"
    looked_up = [url for url in tenant.calls if "/v1.0/groups" in url and "Members" not in url]
    assert all(f"/v1.0/groups/{GROUP_ID}" in url for url in looked_up), looked_up  # by id, not name
