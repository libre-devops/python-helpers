import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest

from fakes.http import json_body, routes
from fakes.ids import SUBSCRIPTION, TENANT
from fakes.tenant import WORKSPACE, invoke, run

RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-soc"
    "/providers/Microsoft.OperationalInsights/workspaces/law-soc"
)
LAW = {"id": RESOURCE_ID, "name": "law-soc", "properties": {"customerId": WORKSPACE}}
HEARTBEAT = (200, {"tables": [{"columns": [{"name": "Computer"}], "rows": [["web01"]]}]})


def test_logs_query_uses_the_profiles_workspace(config_file, tenant):
    result = invoke(config_file, tenant, ["logs", "query", "Heartbeat", "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["Computer", "web01"]
    query = next(r for r in tenant.requests if urlsplit(r.url).hostname == "api.loganalytics.io")
    assert urlsplit(query.url).path == f"/v1/workspaces/{WORKSPACE}/query"


def usage_reply(*rows):
    columns = ["DataType", "LastData", "Megabytes", "BillableMegabytes", "Solutions"]
    return (
        200,
        {"tables": [{"columns": [{"name": name} for name in columns], "rows": list(rows)}]},
    )


def ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_ingestion_lists_quiet_tables_first_and_exits_3(config_file):
    seen = []

    def usage(request):
        seen.append(json_body(request)["query"])
        return usage_reply(
            ["Heartbeat", ago(1), 10.0, 0.0, "LogManagement"],
            ["CommonSecurityLog", ago(50), 5000.0, 5000.0, "Security"],
        )

    handler = routes({f"/v1/workspaces/{WORKSPACE}/query": usage})
    result = run(config_file, handler, ["logs", "ingestion", "--window", "7d", "-o", "csv"])
    assert result.exit_code == 3, result.output
    assert seen[0].startswith("Usage\n| where TimeGenerated > ago(168h)")
    lines = result.stdout.splitlines()
    assert lines[0] == "TABLE,LAST DATA,QUIET FOR,GB,BILLABLE GB,SOLUTIONS"
    assert [line.split(",")[0] for line in lines[1:]] == ["CommonSecurityLog", "Heartbeat"]
    assert "2 table(s) received data in the last 7d: 5.01 GB, 5.00 GB billable" in result.stderr
    assert "1 table(s) quiet for over 1d" in result.stderr
    calm = run(config_file, handler, ["logs", "ingestion", "--quiet-after", "3d", "-o", "json"])
    assert calm.exit_code == 0, calm.output
    records = json.loads(calm.stdout)
    assert [(item["table"], item["quiet"]) for item in records] == [
        ("CommonSecurityLog", False),
        ("Heartbeat", False),
    ]


def test_ingestion_needs_a_workspace(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[microsoft]\ndefault_profile = "t"\n[microsoft.profiles.t]\n'
        'tenant_id = "11111111-1111-1111-1111-111111111111"\n',
        encoding="utf-8",
    )
    result = run(config, routes({}), ["logs", "ingestion"])
    assert "no workspace given" in str(result.exception)


@pytest.mark.parametrize(
    ("given", "kind", "route", "reply"),
    [
        (RESOURCE_ID, "resource id", RESOURCE_ID, LAW),
        ("law-soc", "name", "/providers/Microsoft.ResourceGraph/resources", {"data": [LAW]}),
    ],
    ids=["resource-id", "name"],
)
def test_a_workspace_named_by_resource_id_or_name_is_looked_up(
    config_file, given, kind, route, reply
):
    handler = routes({route: (200, reply), f"/v1/workspaces/{WORKSPACE}/query": HEARTBEAT})
    result = run(config_file, handler, ["logs", "query", "Heartbeat", "-w", given, "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["Computer", "web01"]
    found = f"workspace law-soc in rg-soc, from its {kind}: Workspace ID {WORKSPACE}"
    assert found in result.stderr


def test_the_profiles_workspace_may_be_a_name(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[microsoft.profiles.t]\ntenant_id = "{TENANT}"\nworkspace = "law-soc"\n',
        encoding="utf-8",
    )
    handler = routes(
        {
            "/providers/Microsoft.ResourceGraph/resources": (200, {"data": [LAW]}),
            f"/v1/workspaces/{WORKSPACE}/query": HEARTBEAT,
        }
    )
    result = run(config, handler, ["logs", "query", "Heartbeat", "-p", "t"])
    assert result.exit_code == 0, result.output


def test_the_resource_id_of_something_else_is_refused_before_any_request(config_file):
    vault = RESOURCE_ID.replace(
        "Microsoft.OperationalInsights/workspaces", "Microsoft.KeyVault/vaults"
    )
    result = run(config_file, routes({}), ["logs", "ingestion", "-w", vault])
    assert result.exit_code == 1
    refusal = "resource id of a Microsoft.KeyVault/vaults, not of a Log Analytics workspace"
    assert refusal in str(result.exception)
