import re

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.planner import CLOSED, PLAN_ID, TO_DISCUSS, FakePlanner, task
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import AmbiguousError, ApiError, InputError, NotFoundError
from libre_devops_helpers.microsoft.news import MESSAGE_KEY, ROLLUP_TITLE
from libre_devops_helpers.microsoft.planner import PlannerClient, keyed


def planner(fake=None):
    fake = fake or FakePlanner()
    session, _ = fake_session(fake)
    return PlannerClient.create(StaticTokens(), TENANT, session=session), fake


def test_a_plan_by_title_or_id_and_its_buckets_by_name():
    client, _ = planner()
    assert client.plan("operations").id == PLAN_ID
    assert client.plan(PLAN_ID).title == "Operations"
    with pytest.raises(NotFoundError) as error:
        client.plan("Nope")
    assert "there are: Operations" in error.value.hint
    assert client.bucket(PLAN_ID, "to be discussed").id == TO_DISCUSS
    with pytest.raises(NotFoundError, match="no bucket"):
        client.bucket(PLAN_ID, "Doing")
    with pytest.raises(InputError):
        client.buckets("../x")


def test_two_plans_with_one_title_are_ambiguous(monkeypatch):
    client, _ = planner()
    same = client.plans()[0]
    monkeypatch.setattr(client, "plans", lambda: [same, same])
    with pytest.raises(AmbiguousError):
        client.plan("Operations")


def test_the_plans_tasks_are_keyed_by_what_their_titles_start_with():
    client, _ = planner()
    tasks = client.tasks(PLAN_ID)
    assert [task.done for task in tasks] == [True, False]
    found = keyed(tasks, re.compile(r"^MC[0-9]+", re.IGNORECASE))
    assert list(found) == ["MC1000001"]
    assert found["MC1000001"].bucket_id == CLOSED
    assert list(keyed(tasks, ROLLUP_TITLE)) == ["2026-09"]


def test_a_post_is_found_by_either_way_of_titling_its_task():
    client, fake = planner()
    fake.tasks.append(
        task("TaskSyncAAAAAAAAAAAAAAAAAAAA", "[Microsoft Teams] Teams: recap [MC1000002]")
    )
    fake.tasks.append(task("TaskTalkAAAAAAAAAAAAAAAAAAAA", "Talk about MC1000003 on Friday"))
    assert sorted(keyed(client.tasks(PLAN_ID), MESSAGE_KEY)) == ["MC1000001", "MC1000002"]


def test_a_task_is_read_and_changed_behind_its_etags():
    client, fake = planner()
    rollup = client.tasks(PLAN_ID)[1]
    assert rollup.etag == 'W/"task-TaskTwoAAAAAAAAAAAAAAAAAAAAA"'
    assert client.description(rollup.id) == ""
    client.update_task(
        rollup, title=" Message Center rollup: 2026-09 (4 messages) ", description="all"
    )
    assert fake.tasks[1]["title"] == "Message Center rollup: 2026-09 (4 messages)"
    assert client.description(rollup.id) == "all"
    with pytest.raises(ApiError) as stale:
        client.update_task(rollup, title="again", description="all")
    assert stale.value.status == 412
    with pytest.raises(InputError):
        client.update_task(rollup, title=" ", description="")


def test_a_task_is_made_in_its_bucket_with_its_description_behind_the_etag():
    client, fake = planner()
    made = client.create_task(
        PLAN_ID, TO_DISCUSS, "MC1000003: " + "x" * 300, description="read this"
    )
    assert len(made.title) == 255
    assert fake.details[made.id] == {"description": "read this", "previewType": "description"}
    plain = client.create_task(PLAN_ID, TO_DISCUSS, "No description")
    assert plain.id not in fake.details
    with pytest.raises(InputError):
        client.create_task(PLAN_ID, TO_DISCUSS, "  ")
