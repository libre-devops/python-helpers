"""Message Center and Planner over Graph, made up: posts to read, and a plan whose tasks can
be listed, added to and changed, with Planner's etag checks on a task and its details."""

import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

PLAN_ID = "PlanAAAAAAAAAAAAAAAAAAAAAAAA"
TO_DISCUSS = "BucketDiscussAAAAAAAAAAAAAAA"
CLOSED = "BucketClosedAAAAAAAAAAAAAAAA"


def message(message_id: str, title: str, services=("Microsoft Defender XDR",), **extra) -> dict:
    return {
        "id": message_id,
        "title": title,
        "category": extra.get("category", "planForChange"),
        "severity": extra.get("severity", "normal"),
        "services": list(services),
        "tags": ["Admin impact"],
        "isMajorChange": extra.get("major", False),
        "startDateTime": "2026-09-20T00:00:00Z",
        "endDateTime": "2026-12-31T00:00:00Z",
        "lastModifiedDateTime": extra.get("updated", "2026-09-26T09:00:00Z"),
        "actionRequiredByDateTime": extra.get("action_by"),
        "body": {"contentType": "html", "content": f"<p>{title}: <b>act</b> by Friday.</p>"},
    }


def task(task_id: str, title: str, bucket: str = TO_DISCUSS, percent: int = 0) -> dict:
    return {
        "id": task_id,
        "title": title,
        "planId": PLAN_ID,
        "bucketId": bucket,
        "percentComplete": percent,
        "dueDateTime": None,
        "createdDateTime": "2026-09-21T10:00:00Z",
        "completedDateTime": "2026-09-22T10:00:00Z" if percent == 100 else None,
        "@odata.etag": f'W/"task-{task_id}"',
    }


class FakePlanner:
    """Answers Message Center and Planner calls, and keeps the tasks created."""

    def __init__(self) -> None:
        self.messages = [
            message("MC1000001", "Defender XDR: new hunting tables"),
            message("MC1000002", "Teams: meeting recap", services=("Microsoft Teams",)),
            message(
                "MC1000003",
                "Sentinel: connector retired",
                services=("Microsoft Sentinel",),
                severity="high",
                major=True,
                action_by="2026-10-01T00:00:00Z",
            ),
        ]
        self.tasks = [
            task(
                "TaskOneAAAAAAAAAAAAAAAAAAAAA",
                "MC1000001: Defender XDR: new hunting tables",
                CLOSED,
                100,
            ),
            task("TaskTwoAAAAAAAAAAAAAAAAAAAAA", "Message Center rollup: 2026-09 (3 messages)"),
        ]
        self.details: dict[str, dict] = {}
        self.requests: list[tuple[str, str]] = []
        self.forbid_news = False

    def __call__(self, request):
        parts = urlsplit(request.url)
        path = unquote(parts.path)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        self.requests.append((request.method, unquote(request.url)))
        if path.startswith("/v1.0/admin/serviceAnnouncement/messages"):
            return self.news(path, query)
        if path.startswith("/v1.0/me/planner/plans"):
            return (
                200,
                {
                    "value": [
                        {
                            "id": PLAN_ID,
                            "title": "Operations",
                            "owner": "u1",
                            "createdDateTime": "2026-07-21T16:13:24Z",
                        }
                    ]
                },
            )
        if path.startswith("/v1.0/planner/"):
            return self.planner(request, path)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def news(self, path: str, query: dict[str, str]):
        if self.forbid_news:
            return (403, {"error": {"code": "UnknownError", "message": "Forbidden"}})
        if path.endswith("/messages"):
            wanted = query.get("$filter", "")
            found = [item for item in self.messages if _changed_within(item, wanted)]
            if "isMajorChange eq true" in wanted:
                found = [item for item in found if item["isMajorChange"]]
            if "category eq 'stayInformed'" in wanted:
                found = [item for item in found if item["category"] == "stayInformed"]
            return (200, {"value": found})
        wanted_id = path.rsplit("/", 1)[1]
        for item in self.messages:
            if item["id"] == wanted_id:
                return (200, item)
        return (404, {"error": {"code": "NotFound", "message": "no such message"}})

    def planner(self, request, path: str):
        if path == f"/v1.0/planner/plans/{PLAN_ID}/buckets":
            return (
                200,
                {
                    "value": [
                        {"id": TO_DISCUSS, "name": "To be discussed", "planId": PLAN_ID},
                        {"id": CLOSED, "name": "Closed", "planId": PLAN_ID},
                    ]
                },
            )
        if path == f"/v1.0/planner/plans/{PLAN_ID}/tasks":
            return (200, {"value": self.tasks})
        if path == "/v1.0/planner/tasks" and request.method == "POST":
            body = json.loads(request.body)
            made = task(f"TaskNew{len(self.tasks):021d}", body["title"], body["bucketId"])
            self.tasks.append(made)
            return (201, made)
        if path.endswith("/details"):
            task_id = path.split("/")[4]
            if request.method == "GET":
                written = self.details.get(task_id, {}).get("description", "")
                return (200, {"@odata.etag": f'W/"etag-{task_id}"', "description": written})
            if request.headers.get("If-Match") != f'W/"etag-{task_id}"':
                return (412, {"error": {"code": "PreconditionFailed", "message": "etag"}})
            self.details[task_id] = json.loads(request.body)
            return (204, b"")  # as Graph: no body at all
        if path.startswith("/v1.0/planner/tasks/") and request.method == "PATCH":
            return self.change(request, path.rsplit("/", 1)[1])
        raise AssertionError(f"unexpected Planner request {request.method} {path}")

    def change(self, request, task_id: str):
        found = next(item for item in self.tasks if item["id"] == task_id)
        if request.headers.get("If-Match") != found["@odata.etag"]:
            return (412, {"error": {"code": "PreconditionFailed", "message": "etag"}})
        found.update(json.loads(request.body))
        found["@odata.etag"] = f'W/"task-{task_id}-changed"'
        return (204, b"")


def _changed_within(item: dict, wanted: str) -> bool:
    """Whether a post passes the $filter's lastModifiedDateTime span, when it has both ends
    (as a day or a month does): an open one, such as the last 7 days, comes from the real
    clock, so is let through for tests that do not depend on today's date. These timestamps
    all have one form, so they compare as text."""
    since = re.search(r"lastModifiedDateTime ge (\S+)", wanted)
    until = re.search(r"lastModifiedDateTime lt (\S+)", wanted)
    if since is None or until is None:
        return True
    return since.group(1) <= item["lastModifiedDateTime"] < until.group(1)
