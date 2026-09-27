"""Planner, through Graph: plans, buckets and tasks, and creating a task in a bucket.

Creating a task is the one change this makes, and only when asked: a command offers it
behind an explicit flag, after showing what it would create.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from libre_devops_helpers.core.errors import AmbiguousError, InputError, NotFoundError
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.planner.models import Bucket, Plan, Task

# Planner's ids are 28 characters of letters, digits, _ and -.
_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
TITLE_LIMIT = 255  # the longest title Planner takes


class PlannerClient(GraphServiceClient):
    """Plans, buckets and tasks. Close it (or use ``with``) when done."""

    API_NAME = "Planner (Microsoft Graph)"

    def plans(self) -> list[Plan]:
        """The plans shared with the signed-in user."""
        return [Plan.from_json(item) for item in self.api.get_all("/v1.0/me/planner/plans")]

    def plan(self, ref: str) -> Plan:
        """A plan by its id or its title (ignoring case), among the user's."""
        wanted = ref.strip()
        plans = self.plans()
        found = [
            plan
            for plan in plans
            if wanted in {plan.id, plan.title} or plan.title.casefold() == wanted.casefold()
        ]
        if not found:
            there = ", ".join(plan.title for plan in plans) or "none"
            raise NotFoundError(f"no plan {ref!r} among yours", hint=f"there are: {there}")
        if len(found) > 1:
            raise AmbiguousError(f"{len(found)} plans are called {ref!r}", hint="give its id")
        return found[0]

    def buckets(self, plan_id: str) -> list[Bucket]:
        """The plan's buckets."""
        path = f"/v1.0/planner/plans/{_id(plan_id)}/buckets"
        return [Bucket.from_json(item) for item in self.api.get_all(path)]

    def bucket(self, plan_id: str, name: str) -> Bucket:
        """The plan's bucket called ``name`` (ignoring case)."""
        buckets = self.buckets(plan_id)
        for bucket in buckets:
            if bucket.name.casefold() == name.strip().casefold():
                return bucket
        there = ", ".join(bucket.name for bucket in buckets) or "none"
        raise NotFoundError(f"no bucket {name!r} in the plan", hint=f"there are: {there}")

    def tasks(self, plan_id: str) -> list[Task]:
        """Every task in the plan, done or not."""
        path = f"/v1.0/planner/plans/{_id(plan_id)}/tasks"
        return [Task.from_json(item) for item in self.api.get_all(path)]

    def create_task(
        self, plan_id: str, bucket_id: str, title: str, *, description: str = ""
    ) -> Task:
        """A new task in the bucket, with ``description`` in its details when given."""
        if not title.strip():
            raise InputError("a task needs a title")
        body = {
            "planId": _id(plan_id),
            "bucketId": _id(bucket_id),
            "title": title.strip()[:TITLE_LIMIT],
        }
        task = Task.from_json(self.api.request("POST", "/v1.0/planner/tasks", json_body=body))
        if description:
            self._describe(task.id, description)
        return task

    def _describe(self, task_id: str, description: str) -> None:
        # Planner changes a task's details only with their current etag, which a new task's
        # details have from the moment it is made.
        path = f"/v1.0/planner/tasks/{_id(task_id)}/details"
        etag = str(self.api.get(path).get("@odata.etag", ""))
        self.api.request(
            "PATCH",
            path,
            headers={"If-Match": etag},
            json_body={"description": description, "previewType": "description"},
            allow_empty=True,
        )


def keyed(tasks: Iterable[Task], key: re.Pattern[str]) -> Mapping[str, Task]:
    """The tasks whose title starts with a key ``key`` matches (``MC1183010: ...``), by that
    key: how a plan says which things it has a task for already."""
    found: dict[str, Task] = {}
    for task in tasks:
        match = key.match(task.title.strip())
        if match:
            found.setdefault(match.group(0).upper(), task)
    return found


def _id(value: str) -> str:
    if not _ID.fullmatch(value.strip()):
        raise InputError(f"{value!r} is not a Planner id")
    return value.strip()
