from datetime import UTC, datetime, timedelta, timezone

import pytest

from fakes.http import fake_session
from fakes.ids import TENANT
from fakes.incidents import alert, incident, query
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError
from libre_devops_helpers.microsoft.incidents import (
    OPEN_STATUSES,
    Incident,
    IncidentsClient,
    most_severe,
    newest,
    severities_from,
    summarise,
)
from libre_devops_helpers.microsoft.incidents import client as client_module

BST = timezone(timedelta(hours=1))


def incidents_client(handler):
    session, adapter = fake_session(handler)
    return IncidentsClient.create(StaticTokens(), TENANT, session=session), adapter


def test_the_window_statuses_and_severities_become_one_graph_filter():
    client, adapter = incidents_client(lambda request: (200, {"value": [incident(1)]}))
    found = client.incidents(
        start=datetime(2026, 9, 24, tzinfo=BST),
        end=datetime(2026, 9, 25, tzinfo=BST),
        statuses=OPEN_STATUSES,
        severities=("high",),
    )
    assert [item.id for item in found.incidents] == ["1"]
    sent = query(adapter.requests[0])
    assert sent["$filter"] == (
        "createdDateTime ge 2026-09-23T23:00:00Z and createdDateTime lt 2026-09-24T23:00:00Z"
        " and (status eq 'active' or status eq 'inProgress' or status eq 'awaitingAction')"
        " and severity eq 'high'"
    )
    assert (sent["$expand"], sent["$top"]) == ("alerts", "50")


def test_without_filters_nothing_is_filtered_and_updated_windows_use_the_update_time():
    client, adapter = incidents_client(lambda request: (200, {"value": []}))
    client.incidents()
    assert "$filter" not in query(adapter.requests[0])
    client.incidents(start=datetime(2026, 9, 1, tzinfo=UTC), by="lastUpdateDateTime")
    assert query(adapter.requests[1])["$filter"] == "lastUpdateDateTime ge 2026-09-01T00:00:00Z"
    with pytest.raises(InputError, match="created or updated"):
        client.incidents(by="closedDateTime")
    with pytest.raises(InputError, match="unknown incident status"):
        client.incidents(statuses=("open",))


def test_pages_are_followed_and_a_runaway_listing_is_stopped(monkeypatch):
    def handler(request):
        if "page=2" in request.url:
            return (200, {"value": [incident(3)]})
        return (
            200,
            {
                "value": [incident(1), incident(2)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/security/incidents?page=2",
            },
        )

    client, _ = incidents_client(handler)
    found = client.incidents()
    assert [item.id for item in found.incidents] == ["1", "2", "3"]
    assert not found.truncated
    monkeypatch.setattr(client_module, "MAX_INCIDENTS", 2)
    stopped = client.incidents()
    assert len(stopped.incidents) == 2
    assert stopped.truncated


def test_sources_are_matched_on_the_alerts():
    records = [
        incident(1, sources=("microsoftDefenderForEndpoint",)),
        incident(2, sources=("microsoftSentinel",)),
        incident(3, sources=("microsoftDefenderForOffice365", "microsoftSentinel")),
    ]
    client, _ = incidents_client(lambda request: (200, {"value": records}))
    found = client.incidents(sources=("microsoftSentinel",))
    assert [item.id for item in found.incidents] == ["2", "3"]
    assert found.incidents[1].source_names == ("Office 365", "Sentinel")


def test_one_incident_is_read_with_its_alerts_and_evidence():
    record = incident(
        42,
        alerts=[
            alert(
                evidence=[
                    {
                        "@odata.type": "#microsoft.graph.security.deviceEvidence",
                        "deviceDnsName": "web01",
                    },
                    {
                        "@odata.type": "#microsoft.graph.security.userEvidence",
                        "userAccount": {"userPrincipalName": "ana@example.com"},
                    },
                    {
                        "@odata.type": "#microsoft.graph.security.ipEvidence",
                        "ipAddress": "203.0.113.7",
                    },
                    "not a dict",
                ]
            ),
            alert(
                "microsoftSentinel",
                evidence=[
                    {"@odata.type": "#microsoft.graph.security.deviceEvidence", "hostName": "web01"}
                ],
            ),
        ],
    )
    client, adapter = incidents_client(lambda request: (200, record))
    found = client.incident("42")
    assert found.devices == ("web01",)
    assert found.users == ("ana@example.com",)
    assert found.source_names == ("Endpoint", "Sentinel")
    assert adapter.requests[0].url.split("?")[0].endswith("/v1.0/security/incidents/42")


def test_an_incident_id_must_be_a_number_and_exist():
    client, _ = incidents_client(lambda request: (404, {"error": {"code": "NotFound"}}))
    with pytest.raises(InputError, match="not an incident id"):
        client.incident("../users")
    with pytest.raises(NotFoundError, match="no incident 7"):
        client.incident("7")


def test_a_missing_scope_says_what_the_token_needs():
    denied = (403, {"error": {"code": "Forbidden", "message": "Missing scopes"}})
    client, _ = incidents_client(lambda request: denied)
    for call in (lambda: client.incidents(), lambda: client.incident("1")):
        with pytest.raises(ApiError) as caught:
            call()
        assert "SecurityIncident.Read.All" in (caught.value.hint or "")


def made(records: list[dict]) -> list[Incident]:
    return [Incident.from_graph(record) for record in records]


def test_ordering_by_severity_then_newest_and_by_newest():
    found = made(
        [
            incident(1, severity="low", created="2026-09-24T10:00:00Z"),
            incident(2, severity="high", created="2026-09-24T08:00:00Z"),
            incident(3, severity="high", created="2026-09-24T09:00:00Z"),
            incident(4, severity="unknown", created="2026-09-24T11:00:00Z", createdDateTime=None),
        ]
    )
    assert [item.id for item in most_severe(found)] == ["3", "2", "1", "4"]
    assert [item.id for item in newest(found)] == ["1", "3", "2", "4"]


def test_summary_counts_by_severity_status_and_source():
    counts = summarise(
        made(
            [
                incident(1, severity="high", sources=("microsoftSentinel",)),
                incident(2, severity="high", status="resolved"),
                incident(
                    3, severity="low", sources=("microsoftSentinel", "microsoftDefenderForEndpoint")
                ),
            ]
        )
    )
    assert counts.total == 3
    assert counts.by_severity == {"high": 2, "low": 1}
    assert counts.by_status == {"active": 2, "resolved": 1}
    assert counts.by_source == {"Sentinel": 2, "Endpoint": 2}


def test_severities_at_or_above_a_minimum():
    assert severities_from("medium") == ("high", "medium")
    assert severities_from("INFORMATIONAL") == ("high", "medium", "low", "informational")
    with pytest.raises(InputError, match="unknown severity"):
        severities_from("critical")


def test_an_incident_knows_whether_it_is_open():
    assert Incident.from_graph(incident(1, status="awaitingAction")).open
    assert not Incident.from_graph(incident(1, status="resolved")).open


def test_a_suspended_service_keeps_its_own_hint():
    suspended = (403, {"error": {"code": "Unauthorized", "message": "Account mode: Suspended"}})
    client, _ = incidents_client(lambda request: suspended)
    with pytest.raises(ApiError) as caught:
        client.incidents()
    assert "suspended in this tenant" in (caught.value.hint or "")
