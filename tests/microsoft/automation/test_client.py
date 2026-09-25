import pytest

from fakes.automation import ACCOUNT_ID, FakeAutomation, account
from fakes.http import fake_session
from fakes.ids import OTHER_SUBSCRIPTION, SUBSCRIPTION, TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import AmbiguousError, InputError, NotFoundError
from libre_devops_helpers.microsoft.automation import AutomationClient

SUBSCRIPTIONS = [SUBSCRIPTION, OTHER_SUBSCRIPTION]


def client(fake: FakeAutomation) -> AutomationClient:
    session, _ = fake_session(fake.handler)
    return AutomationClient.create(StaticTokens(), TENANT, session=session)


def test_an_account_is_found_by_name_across_subscriptions():
    found = client(FakeAutomation()).find_account("AA-OPS", SUBSCRIPTIONS)
    assert (found.name, found.resource_group, found.subscription_id) == (
        "aa-ops",
        "rg-ops",
        SUBSCRIPTION,
    )


def test_an_account_is_found_by_resource_id_without_listing():
    fake = FakeAutomation()
    found = client(fake).find_account(ACCOUNT_ID, [])
    assert found.id == ACCOUNT_ID
    assert all(
        "/providers/Microsoft.Automation/automationAccounts?" not in url for url in fake.requests
    )


def test_a_shared_name_is_refused_unless_the_resource_group_settles_it():
    fake = FakeAutomation()
    fake.accounts[OTHER_SUBSCRIPTION] = [account(group="rg-dev", subscription=OTHER_SUBSCRIPTION)]
    with pytest.raises(AmbiguousError) as caught:
        client(fake).find_account("aa-ops", SUBSCRIPTIONS)
    assert "rg-dev" in (caught.value.hint or "")
    found = client(fake).find_account("aa-ops", SUBSCRIPTIONS, resource_group="RG-DEV")
    assert found.subscription_id == OTHER_SUBSCRIPTION


def test_a_missing_account_names_where_it_looked():
    with pytest.raises(NotFoundError, match="in resource group rg-x"):
        client(FakeAutomation()).find_account("aa-nope", SUBSCRIPTIONS, resource_group="rg-x")


@pytest.mark.parametrize("ref", ["aa/../x", "aa ops", ""])
def test_names_that_could_reach_another_resource_are_refused(ref):
    with pytest.raises(InputError):
        client(FakeAutomation()).find_account(ref, SUBSCRIPTIONS)


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        (
            ACCOUNT_ID.replace("Microsoft.Automation/automationAccounts", "Microsoft.Web/sites"),
            "it is the resource id of a Microsoft.Web/sites",
        ),
        (f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/x", "expected providers/NAMESPACE"),
        (ACCOUNT_ID.replace("aa-ops", "aa..ops"), "not an Automation account name"),
    ],
    ids=["another-type", "not-an-id", "bad-name"],
)
def test_a_resource_id_that_is_not_an_accounts_is_refused_before_any_request(ref, message):
    fake = FakeAutomation()
    with pytest.raises(InputError) as caught:
        client(fake).find_account(ref, SUBSCRIPTIONS)
    assert message in f"{caught.value} {caught.value.hint}"


def test_jobs_are_every_page_newest_first():
    automation = client(FakeAutomation())
    jobs = automation.jobs(automation.find_account("aa-ops", SUBSCRIPTIONS))
    assert [(job.id, job.runbook, job.status) for job in jobs] == [
        ("job-3", "Rotate-Keys", "Failed"),
        ("job-2", "Patch-Servers", "Completed"),
        ("job-1", "Rotate-Keys", "Completed"),
    ]
    assert jobs[0].failed
    assert not jobs[1].failed


def test_one_job_carries_who_started_it_and_why_it_failed():
    automation = client(FakeAutomation())
    found = automation.job(automation.find_account(ACCOUNT_ID, []), "job-3")
    assert found.started_by == "Schedule: nightly"
    assert "Forbidden" in found.exception
    with pytest.raises(NotFoundError):
        automation.job(automation.find_account(ACCOUNT_ID, []), "job-9")
    with pytest.raises(InputError):
        automation.job(automation.find_account(ACCOUNT_ID, []), "../../x")


def test_streams_come_oldest_first_and_one_can_be_read_in_full():
    automation = client(FakeAutomation())
    aa = automation.find_account(ACCOUNT_ID, [])
    streams = automation.streams(aa, "job-3")
    assert [(item.stream, item.summary) for item in streams] == [
        ("Output", "Rotating 3 keys"),
        ("Warning", "Retrying kv-app-prd"),
        ("Error", "Forbidden"),
    ]
    full = automation.stream(aa, "job-3", "s2")
    assert full.message.startswith("Forbidden: the caller has no get permission")
    for bad in ("s2/../x", "s2\n"):  # a trailing line break is not let through either
        with pytest.raises(InputError):
            automation.stream(aa, "job-3", bad)


def test_output_is_the_jobs_text():
    automation = client(FakeAutomation())
    assert (
        automation.output(automation.find_account(ACCOUNT_ID, []), "job-2")
        == "Patched 12 servers\n"
    )
