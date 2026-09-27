"""A fake Atlassian Cloud site: Jira's and Confluence's REST APIs, as the real one pages them,
refusing any request without the right email and API token."""

import base64
from urllib.parse import parse_qs, unquote, urlsplit

SITE = "https://contoso.atlassian.net"
EMAIL = "ana@example.com"
TOKEN = "atl-token"
ENV = {"JIRA_INSTANCE": SITE, "JIRA_EMAIL": EMAIL, "JIRA_TOKEN": TOKEN}


def issue(key: str, summary: str, status: str = "To Do", category: str = "To Do", **extra) -> dict:
    fields = {
        "summary": summary,
        "status": {"name": status, "statusCategory": {"name": category}},
        "issuetype": {"name": "Task"},
        "priority": {"name": "Medium"},
        "assignee": {"displayName": "Ana"} if extra.get("assigned", True) else None,
        "reporter": {"displayName": "Ben"},
        "project": {"key": key.split("-")[0]},
        "labels": ["linux"],
        "created": "2026-09-20T09:00:00.000+0000",
        "updated": "2026-09-25T09:00:00.000+0000",
    }
    return {"id": str(10000 + int(key.split("-")[1])), "key": key, "fields": fields}


def page(page_id: str, title: str, space_id: str = "1") -> dict:
    return {
        "id": page_id,
        "title": title,
        "spaceId": space_id,
        "status": "current",
        "version": {"number": 3, "createdAt": "2026-09-24T10:00:00.000Z"},
        "_links": {"webui": f"/spaces/OPS/pages/{page_id}/{title.replace(' ', '+')}"},
    }


class FakeSite:
    """Jira and Confluence for one site, a few records of each."""

    def __init__(self) -> None:
        self.issues = [issue(f"OPS-{n}", f"Patch web0{n}") for n in range(1, 6)]
        self.issues[1] = issue("OPS-2", "Rotate keys", "In Progress", "In Progress", assigned=False)
        self.description = "<p>Patch <strong>web01</strong> tonight.</p><ul><li>drain</li></ul>"
        self.spaces = [
            {
                "id": "1",
                "key": "OPS",
                "name": "Operations",
                "type": "global",
                "status": "current",
                "_links": {"webui": "/spaces/OPS"},
            },
            {
                "id": "2",
                "key": "~acc1",
                "name": "Ana",
                "type": "personal",
                "status": "current",
                "_links": {"webui": "/spaces/~acc1"},
            },
        ]
        self.pages = [page("101", "Runbook"), page("102", "On-call"), page("201", "Notes", "2")]
        self.body = "<h2>Restart</h2><p>Run <code>systemctl restart app</code>.</p>"
        self.requests: list[str] = []

    def __call__(self, request):
        url = unquote(request.url)
        self.requests.append(url)
        expected = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        if request.headers.get("Authorization") != f"Basic {expected}":
            return (
                401,
                {"errorMessages": ["Client must be authenticated to access this resource."]},
            )
        parts = urlsplit(request.url)
        path = unquote(parts.path)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if path.startswith("/rest/api/3/"):
            return self.jira(path.removeprefix("/rest/api/3"), query)
        if path.startswith("/wiki/"):
            return self.confluence(path.removeprefix("/wiki"), query)
        raise AssertionError(f"unexpected Atlassian request {url}")

    def jira(self, path: str, query: dict[str, str]):
        if path == "/myself":
            return (
                200,
                {
                    "accountId": "acc1",
                    "displayName": "Ana",
                    "emailAddress": EMAIL,
                    "active": True,
                    "timeZone": "Europe/London",
                },
            )
        if path == "/search/jql":
            if "order by" in query["jql"].lower() and query["jql"].lower().startswith("order by"):
                return (400, {"errorMessages": ["Unbounded JQL queries are not allowed here."]})
            start = int(query.get("nextPageToken", "0"))
            size = int(query.get("maxResults", "50"))
            chunk = self.issues[start : start + size]
            done = start + size >= len(self.issues)
            body = {"issues": chunk, "isLast": done}
            if not done:
                body["nextPageToken"] = str(start + size)
            return (200, body)
        if path.startswith("/issue/"):
            key = path.removeprefix("/issue/")
            found = next((item for item in self.issues if item["key"] == key), None)
            if found is None:
                return (
                    404,
                    {
                        "errorMessages": [
                            "Issue does not exist or you do not have permission to see it."
                        ]
                    },
                )
            return (200, {**found, "renderedFields": {"description": self.description}})
        if path == "/project/search":
            start = int(query.get("startAt", "0"))
            projects = [
                {"id": "1", "key": "OPS", "name": "Operations", "projectTypeKey": "software"},
                {"id": "2", "key": "SEC", "name": "Security", "projectTypeKey": "business"},
            ]
            chunk = projects[start : start + 1]  # one a page, to be paged through
            return (200, {"values": chunk, "isLast": start + 1 >= len(projects), "startAt": start})
        raise AssertionError(f"unexpected Jira path {path}")

    def confluence(self, path: str, query: dict[str, str]):
        if path == "/api/v2/spaces":
            if "keys" in query:
                return (200, {"results": [s for s in self.spaces if s["key"] == query["keys"]]})
            if query.get("cursor") == "2":
                return (200, {"results": self.spaces[1:], "_links": {}})
            return (
                200,
                {"results": self.spaces[:1], "_links": {"next": "/wiki/api/v2/spaces?cursor=2"}},
            )
        if path.startswith("/api/v2/spaces/") and path.endswith("/pages"):
            space = path.split("/")[4]
            return (
                200,
                {"results": self._titled([p for p in self.pages if p["spaceId"] == space], query)},
            )
        if path == "/api/v2/pages":
            return (200, {"results": self._titled(self.pages, query)})
        if path.startswith("/api/v2/pages/"):
            found = next((p for p in self.pages if p["id"] == path.rsplit("/", 1)[1]), None)
            if found is None:
                return (
                    404,
                    {"errors": [{"status": 404, "title": "Not Found", "detail": "no such page"}]},
                )
            return (
                200,
                {**found, "body": {"storage": {"representation": "storage", "value": self.body}}},
            )
        if path == "/rest/api/search":
            hit = {
                "content": {"id": "101", "type": "page", "title": "Runbook"},
                "title": "Runbook",
                "url": "/spaces/OPS/pages/101/Runbook",
                "resultGlobalContainer": {"title": "Operations"},
                "lastModified": "2026-09-24T10:00:00.000Z",
                "excerpt": "restart the\n app",
            }
            return (200, {"results": [hit], "_links": {}})
        raise AssertionError(f"unexpected Confluence path {path}")

    @staticmethod
    def _titled(pages: list[dict], query: dict[str, str]) -> list[dict]:
        title = query.get("title")
        return [p for p in pages if title is None or p["title"] == title]
