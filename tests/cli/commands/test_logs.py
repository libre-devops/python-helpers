from urllib.parse import urlsplit

from fakes.tenant import WORKSPACE, invoke


def test_logs_query_uses_the_profiles_workspace(config_file, tenant):
    result = invoke(config_file, tenant, ["logs", "query", "Heartbeat", "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["Computer", "web01"]
    query = next(r for r in tenant.requests if "api.loganalytics.io" in r.url)
    assert urlsplit(query.url).path == f"/v1/workspaces/{WORKSPACE}/query"
