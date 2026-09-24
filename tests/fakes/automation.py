"""A fake Azure Automation estate, answering the ARM calls the automation client makes."""

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit

from fakes.ids import OTHER_SUBSCRIPTION, SUBSCRIPTION, TENANT

PROVIDER = "providers/Microsoft.Automation/automationAccounts"


def account_id(name: str = "aa-ops", group: str = "rg-ops", subscription: str = SUBSCRIPTION):
    return f"/subscriptions/{subscription}/resourceGroups/{group}/{PROVIDER}/{name}"


ACCOUNT_ID = account_id()


def account(name: str = "aa-ops", group: str = "rg-ops", subscription: str = SUBSCRIPTION):
    return {"id": account_id(name, group, subscription), "name": name, "location": "uksouth"}


def ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def job(job_id: str, runbook: str, status: str, hours_ago: float, **extra) -> dict:
    created = ago(hours_ago)
    finished = status not in {"Running", "New", "Activating"}
    ended = ago(hours_ago - 42 / 3600) if finished else None
    return {
        "id": f"{ACCOUNT_ID}/jobs/{job_id}",
        "name": job_id,
        "properties": {
            "jobId": job_id,
            "runbook": {"name": runbook},
            "status": status,
            "creationTime": created,
            "startTime": created,
            "endTime": ended,
            "runOn": "",
            **extra,
        },
    }


def stream(stream_id: str, kind: str, summary: str, time: str) -> dict:
    return {
        "id": f"{ACCOUNT_ID}/jobs/x/streams/{stream_id}",
        "properties": {
            "jobStreamId": stream_id,
            "streamType": kind,
            "summary": summary,
            "time": time,
        },
    }


class FakeAutomation:
    """One account, aa-ops, with three jobs of two runbooks; every request is recorded."""

    def __init__(self) -> None:
        self.accounts = {SUBSCRIPTION: [account()], OTHER_SUBSCRIPTION: []}
        self.jobs = [
            job("job-3", "Rotate-Keys", "Failed", 1),
            job("job-2", "Patch-Servers", "Completed", 2),
            job("job-1", "Rotate-Keys", "Completed", 25),
        ]
        self.details = {
            "job-3": {
                "startedBy": "Schedule: nightly",
                "exception": "Key Vault kv-app-prd refused the request: Forbidden",
            }
        }
        self.streams = {
            "job-3": [
                stream("s2", "Error", "Forbidden", "2026-09-24T09:00:30Z"),
                stream("s1", "Output", "Rotating 3 keys", "2026-09-24T09:00:10Z"),
                stream("s3", "Warning", "Retrying kv-app-prd", "2026-09-24T09:00:20Z"),
            ],
            "job-2": [stream("s1", "Output", "Patched 12 servers", "2026-09-24T08:00:10Z")],
            "job-1": [],
        }
        self.full = {"s2": "Forbidden: the caller has no get permission on secrets in kv-app-prd"}
        self.outputs = {"job-3": "Rotating 3 keys\n", "job-2": "Patched 12 servers\n"}
        self.requests: list[str] = []

    def handler(self, request):
        url = unquote(request.url)
        self.requests.append(url)
        path = urlsplit(request.url).path
        if path == "/subscriptions":
            return (
                200,
                {
                    "value": [
                        {"subscriptionId": sub, "displayName": name, "tenantId": TENANT}
                        for sub, name in ((SUBSCRIPTION, "Production"), (OTHER_SUBSCRIPTION, "Dev"))
                    ]
                },
            )
        for subscription, accounts in self.accounts.items():
            if path == f"/subscriptions/{subscription}/{PROVIDER}":
                return (200, {"value": accounts})
        for listed in [item for accounts in self.accounts.values() for item in accounts]:
            if path == listed["id"]:
                return (200, listed)
        if path == f"{ACCOUNT_ID}/jobs":
            # Two pages, as ARM pages long lists.
            if "page=2" in url:
                return (200, {"value": self.jobs[2:]})
            next_link = f"https://management.azure.com{ACCOUNT_ID}/jobs?api-version=x&page=2"
            return (200, {"value": self.jobs[:2], "nextLink": next_link})
        prefix = f"{ACCOUNT_ID}/jobs/"
        if path.startswith(prefix):
            job_id, _, rest = path.removeprefix(prefix).partition("/")
            found = next((item for item in self.jobs if item["name"] == job_id), None)
            if found is None:
                return (404, {"error": {"code": "NotFound", "message": "job not found"}})
            if not rest:
                detailed = {**found["properties"], **self.details.get(job_id, {})}
                return (200, {**found, "properties": detailed})
            if rest == "output":
                return (200, self.outputs.get(job_id, "").encode(), {"Content-Type": "text/plain"})
            if rest == "streams":
                return (200, {"value": self.streams[job_id]})
            if rest.startswith("streams/"):
                stream_id = rest.removeprefix("streams/")
                listed = next(
                    s for s in self.streams[job_id] if s["properties"]["jobStreamId"] == stream_id
                )
                full = {**listed["properties"], "streamText": self.full.get(stream_id, "")}
                return (200, {**listed, "properties": full})
        raise AssertionError(f"unexpected request {url}")
