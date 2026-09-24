from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from fakes import TENANT, FakeClock, StaticTokens, fake_session
from libre_devops_helpers.core.errors import ApiError, InputError, LdoError
from libre_devops_helpers.core.poll import PollLimits
from libre_devops_helpers.microsoft.devices import (
    DeviceChecker,
    Expectations,
    inspect_device,
    watch,
)
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.xdr import XdrClient

GROUP_ID = "55555555-5555-5555-5555-555555555555"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def object_id(name: str) -> str:
    return f"{abs(hash(name)) % 10**8:08d}-0000-4000-8000-000000000000"


def device_id(name: str) -> str:
    return f"{abs(hash(name + 'd')) % 10**8:08d}-1111-4111-8111-111111111111"


class FakeTenant:
    """Entra and Defender for a handful of devices, changeable between passes."""

    def __init__(self) -> None:
        self.entra: dict[str, list[dict]] = {}
        self.machines: dict[str, list[dict]] = {}
        self.group_members: list[str] = []
        self.fail: dict[str, tuple[int, dict]] = {}
        self.calls: list[str] = []

    def add(self, name: str, *, onboarded: bool = True, tags=(), last_seen="2026-09-24T11:00:00Z"):
        self.entra.setdefault(name, []).append(
            {
                "id": object_id(name),
                "displayName": name,
                "deviceId": device_id(name),
                "accountEnabled": True,
            }
        )
        self.machines.setdefault(name, []).append(
            {
                "id": (name * 40)[:40].encode().hex()[:40],
                "computerDnsName": name,
                "onboardingStatus": "Onboarded" if onboarded else "CanBeOnboarded",
                "healthStatus": "Active",
                "lastSeen": last_seen,
                "machineTags": list(tags),
                "aadDeviceId": device_id(name),
            }
        )

    def handler(self, request):
        url = unquote(request.url)
        parts = urlsplit(request.url)
        query = parse_qs(parts.query)
        self.calls.append(url)
        for fragment, reply in self.fail.items():
            if fragment in url:
                return reply
        if parts.path == "/v1.0/devices":
            name = query["$filter"][0].split("'")[1]
            return (200, {"value": self.entra.get(name, [])})
        if parts.path == "/v1.0/groups":
            return (200, {"value": [{"id": GROUP_ID, "displayName": "Pilot"}]})
        if parts.path.endswith("/transitiveMembers/microsoft.graph.device"):
            return (200, {"value": [{"id": object_id(name)} for name in self.group_members]})
        if parts.path.endswith("/transitiveMemberOf/microsoft.graph.group"):
            return (200, {"value": [{"id": GROUP_ID, "displayName": "Pilot"}]})
        if parts.path == "/api/machines":
            name = query["$filter"][0].split("'")[1]
            return (200, {"value": self.machines.get(name, [])})
        raise AssertionError(f"unexpected request {url}")

    def defender_calls(self, name: str) -> int:
        return sum(1 for url in self.calls if "/api/machines" in url and f"'{name}'" in url)


def clients(tenant: FakeTenant):
    session, _ = fake_session(tenant.handler)
    tokens = StaticTokens()
    return (
        EntraClient.create(tokens, TENANT, session=session),
        XdrClient.create(tokens, TENANT, session=session),
    )


def checker(tenant: FakeTenant, **options) -> DeviceChecker:
    entra, xdr = clients(tenant)
    return DeviceChecker(entra=entra, xdr=xdr, clock=lambda: NOW, **options)


def statuses(run, name: str) -> dict[str, str]:
    report = next(report for report in run.reports if report.name == name)
    return {outcome.check: outcome.status for outcome in report.outcomes}


# One fast pass --------------------------------------------------------------------


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
    with pytest.raises(LdoError, match="Defender"):
        DeviceChecker(entra=entra).check(["web01"], Expectations())


def test_expectations_need_at_least_one_check():
    with pytest.raises(InputError, match="nothing to check"):
        Expectations(in_entra=False, onboarded=False)


# Watching until done --------------------------------------------------------------


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


# One device across services -------------------------------------------------------


def test_show_finds_nothing_wrong_with_a_healthy_device():
    tenant = FakeTenant()
    tenant.add("web01")
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, now=NOW)
    assert [(f.level, f.message) for f in view.findings] == [("ok", "nothing looks wrong")]
    assert view.groups[object_id("web01")][0].display_name == "Pilot"


def test_show_reports_duplicates_staleness_and_a_broken_entra_link():
    tenant = FakeTenant()
    tenant.add("web01", last_seen="2026-09-01T00:00:00Z")
    tenant.add("web01", last_seen="2026-08-01T00:00:00Z")
    tenant.machines["web01"][0]["aadDeviceId"] = "abcdabcd-0000-4000-8000-000000000000"
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, stale_after=timedelta(days=7), now=NOW)
    messages = [f.message for f in view.findings if f.level == "warn"]
    assert any("2 Entra objects share this name" in m for m in messages)
    assert any("2 Defender records" in m for m in messages)
    assert any(m.startswith("Defender last saw it") for m in messages)
    assert any("which is not one of the Entra objects" in m for m in messages)


def test_show_keeps_going_when_defender_cannot_be_read():
    tenant = FakeTenant()
    tenant.add("web01")
    tenant.fail["/api/machines"] = (
        403,
        {"error": {"code": "Unauthorized", "message": "Suspended account mode"}},
    )
    entra, xdr = clients(tenant)
    view = inspect_device("web01", entra=entra, xdr=xdr, now=NOW)
    assert view.defender is None
    assert any("Defender could not be read" in f.message for f in view.findings)
    assert view.entra
