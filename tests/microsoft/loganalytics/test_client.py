from datetime import timedelta
from urllib.parse import urlsplit

import pytest

from fakes.http import fake_session, json_body
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.microsoft.loganalytics import LogAnalyticsClient

WORKSPACE = "abababab-abab-abab-abab-abababababab"

TABLE = {
    "name": "PrimaryResult",
    "columns": [{"name": "Computer", "type": "string"}, {"name": "count_", "type": "long"}],
    "rows": [["web01", 12], ["web02", 3]],
}


def logs(handler):
    session, adapter = fake_session(handler)
    tokens = StaticTokens()
    return LogAnalyticsClient.create(tokens, TENANT, session=session), adapter, tokens


def test_query_posts_kql_and_timespan_and_reads_the_first_table():
    client, adapter, tokens = logs(lambda request: (200, {"tables": [TABLE]}))
    result = client.query(
        WORKSPACE, "Heartbeat | summarize count() by Computer", timespan=timedelta(days=1)
    )
    assert result.columns == ("Computer", "count_")
    assert result.rows[0] == {"Computer": "web01", "count_": 12}
    request = adapter.requests[0]
    assert urlsplit(request.url).path == f"/v1/workspaces/{WORKSPACE}/query"
    assert json_body(request) == {
        "query": "Heartbeat | summarize count() by Computer",
        "timespan": "PT86400S",
    }
    assert tokens.calls[0] == ("https://api.loganalytics.io", TENANT)


def test_a_partial_result_carries_the_service_warning():
    reply = {"tables": [TABLE], "error": {"code": "PartialError", "message": "query hit a limit"}}
    client, _, _ = logs(lambda request: (200, reply))
    result = client.query(WORKSPACE, "Heartbeat")
    assert result.warnings == ("query hit a limit",)
    assert len(result.rows) == 2


def test_an_error_with_no_table_fails():
    client, _, _ = logs(lambda request: (200, {"error": {"code": "BadQuery", "message": "syntax"}}))
    with pytest.raises(ApiError, match="syntax"):
        client.query(WORKSPACE, "Heartbeat |")


def test_a_resource_id_is_refused_as_one():
    client, adapter, _ = logs(lambda request: (200, {}))
    resource_id = (
        f"/subscriptions/{TENANT}/resourceGroups/rg-soc"
        "/providers/Microsoft.OperationalInsights/workspaces/law-soc"
    )
    with pytest.raises(InputError, match="resource id") as caught:
        client.query(resource_id, "Heartbeat")
    assert "Workspace ID" in (caught.value.hint or "")
    assert adapter.requests == []


def test_the_workspace_must_be_its_guid():
    client, adapter, _ = logs(lambda request: (200, {}))
    with pytest.raises(InputError, match="Workspace ID"):
        client.query("law-soc", "Heartbeat")
    assert adapter.requests == []
