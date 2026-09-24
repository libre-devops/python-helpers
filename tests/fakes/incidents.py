"""Graph security API incidents and alerts, shaped as the real API returns them."""

from urllib.parse import parse_qs, urlsplit

WEB = "https://security.microsoft.com/incidents"


def alert(source: str = "microsoftDefenderForEndpoint", *, severity: str = "high", **extra) -> dict:
    record = {
        "id": f"da-{source}-{severity}",
        "title": f"{severity} alert from {source}",
        "severity": severity,
        "status": "new",
        "serviceSource": source,
        "detectionSource": "antivirus",
        "createdDateTime": "2026-09-24T09:00:00Z",
        "evidence": [],
    }
    record.update(extra)
    return record


def incident(
    number: int,
    *,
    severity: str = "high",
    status: str = "active",
    created: str = "2026-09-24T09:00:00Z",
    sources: tuple[str, ...] = ("microsoftDefenderForEndpoint",),
    **extra,
) -> dict:
    record = {
        "id": str(number),
        "displayName": f"Incident {number}",
        "severity": severity,
        "status": status,
        "createdDateTime": created,
        "lastUpdateDateTime": created,
        "assignedTo": None,
        "classification": "unknown",
        "determination": "unknown",
        "incidentWebUrl": f"{WEB}/{number}",
        "customTags": [],
        "systemTags": [],
        "alerts": [alert(source, severity=severity) for source in sources],
    }
    record.update(extra)
    return record


def query(request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(request.url).query).items()}
