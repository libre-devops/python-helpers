"""End-to-end CLI tests for the command groups, over one fake tenant. No network, no az."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from typer.testing import CliRunner

from fakes import (
    SUBSCRIPTION,
    TENANT,
    FakeClock,
    account_json,
    az_runner,
    fake_session,
    form_body,
    graph_claims,
    json_body,
    make_jwt,
)
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.runtime import Runtime

CLIENT_ID = "77777777-7777-7777-7777-777777777777"
WORKSPACE = "abababab-abab-abab-abab-abababababab"
USER_ID = "88888888-8888-8888-8888-888888888888"
NOW = datetime.now(UTC)

CONFIG = f"""
[microsoft]
default_profile = "tenant"

[microsoft.profiles.tenant]
tenant_id = "{TENANT}"
workspace_id = "{WORKSPACE}"

[microsoft.profiles.app]
tenant_id = "{TENANT}"
auth = "client-secret"
client_id = "{CLIENT_ID}"
"""

runner = CliRunner()


def iso(days: float) -> str:
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def az_responder(args: list[str]) -> tuple[int, str, str]:
    if args[:2] == ["account", "list"]:
        return (0, json.dumps([account_json(SUBSCRIPTION, TENANT, default=True)]), "")
    if args[:2] == ["account", "get-access-token"]:
        resource = args[args.index("--resource") + 1]
        token = make_jwt(graph_claims(aud=resource.rstrip("/")))
        expires = int(NOW.timestamp()) + 3600
        return (0, json.dumps({"accessToken": token, "expires_on": expires}), "")
    raise AssertionError(f"unexpected az call: {args}")


class Tenant:
    """Replies for every API the commands call, keyed on host and path."""

    def __init__(self) -> None:
        self.devices = {"web01"}
        self.machines = {"web01"}
        self.requests: list = []
        # Called before every request, so a test can change the tenant over time.
        self.before = lambda: None

    def __call__(self, request):
        self.before()
        self.requests.append(request)
        parts = urlsplit(request.url)
        host, path = parts.netloc, parts.path
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        name = query.get("$filter", "").split("'")[1] if "'" in query.get("$filter", "") else ""
        if host == "login.microsoftonline.com":
            return (
                200,
                {"access_token": make_jwt(graph_claims(appid=CLIENT_ID)), "expires_in": 3600},
            )
        if host == "graph.microsoft.com":
            return self.graph(path, name)
        if host == "api.securitycenter.microsoft.com":
            return self.defender(path, name)
        if host == "management.azure.com":
            return self.arm(request, path)
        if host == "api.loganalytics.io":
            table = {"columns": [{"name": "Computer"}], "rows": [["web01"]]}
            return (200, {"tables": [table]})
        if host == "kv-app.vault.azure.net":
            if path == "/secrets":
                item = {
                    "id": "https://kv-app.vault.azure.net/secrets/db",
                    "attributes": {"exp": int((NOW + timedelta(days=5)).timestamp())},
                }
                return (200, {"value": [item]})
            return (200, {"value": []})
        raise AssertionError(f"unexpected request {unquote(request.url)}")

    def graph(self, path: str, name: str):
        if path == "/v1.0/devices":
            found = (
                [{"id": USER_ID, "displayName": name, "accountEnabled": True}]
                if name in self.devices
                else []
            )
            return (200, {"value": found})
        if path.endswith("/transitiveMemberOf/microsoft.graph.group"):
            return (200, {"value": []})
        if path == "/v1.0/users/ana@example.com":
            return (
                200,
                {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"},
            )
        if path == "/v1.0/identity/conditionalAccess/policies":
            return (200, {"value": []})
        if path == "/v1.0/applications":
            app = {
                "id": "o1",
                "appId": "a1",
                "displayName": "billing-api",
                "passwordCredentials": [
                    {"keyId": "k1", "displayName": "ci", "endDateTime": iso(3)}
                ],
                "keyCredentials": [],
            }
            return (200, {"value": [app]})
        raise AssertionError(f"unexpected Graph path {path}")

    def defender(self, path: str, name: str):
        if path == "/api/machines":
            found = (
                [
                    {
                        "id": "a" * 40,
                        "computerDnsName": name,
                        "onboardingStatus": "Onboarded",
                        "healthStatus": "Active",
                        "lastSeen": iso(0),
                    }
                ]
                if name in self.machines
                else []
            )
            return (200, {"value": found})
        if path == "/api/advancedqueries/run":
            return (200, {"Schema": [{"Name": "DeviceName"}], "Results": [{"DeviceName": "web01"}]})
        raise AssertionError(f"unexpected Defender path {path}")

    def arm(self, request, path: str):
        if path == "/providers/Microsoft.ResourceGraph/resources":
            return (200, {"data": [{"name": "kv-app", "type": "microsoft.keyvault/vaults"}]})
        if path.endswith("/roleAssignments"):
            item = {
                "id": "ra1",
                "properties": {
                    "scope": f"/subscriptions/{SUBSCRIPTION}",
                    "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/r",
                    "principalId": USER_ID,
                    "principalType": "User",
                },
            }
            return (200, {"value": [item]})
        if "roleDefinitions" in path:
            return (200, {"properties": {"roleName": "Reader"}})
        raise AssertionError(f"unexpected ARM path {path}")


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def tenant():
    return Tenant()


def invoke(config_file, tenant, args, *, environ=None, clock=None, stdin=None):
    obj = Runtime(
        config_path=config_file,
        az_runner=az_runner(az_responder)[0],
        session=fake_session(tenant)[0],
        environ=environ or {},
    )
    if clock is not None:
        obj.clock, obj.sleep = clock, clock.sleep
    return runner.invoke(app, args, obj=obj, input=stdin)


# devices -------------------------------------------------------------------------


def test_devices_check_exits_3_and_says_which_device_is_short(config_file, tenant):
    result = invoke(config_file, tenant, ["devices", "check", "web01,web02", "-o", "json"])
    assert result.exit_code == 3, result.output
    report = json.loads(result.stdout)
    assert not report["complete"]
    by_name = {device["name"]: device for device in report["devices"]}
    assert by_name["web01"]["complete"]
    assert by_name["web02"]["checks"]["defender"]["detail"] == "no Defender record"


def test_devices_check_reads_names_from_a_csv_column(config_file, tenant, tmp_path):
    hosts = tmp_path / "plan.csv"
    hosts.write_text("FQDN,Ring\nweb01,1\n", encoding="utf-8")
    result = invoke(
        config_file, tenant, ["devices", "check", "-f", str(hosts), "--column", "fqdn", "-o", "csv"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["DEVICE,ENTRA,DEFENDER", "web01,ok,ok"]


def test_devices_watch_waits_on_the_fake_clock_until_complete(config_file, tenant):
    clock = FakeClock()

    def arrive_after_ten_minutes():
        if clock.now >= 600:
            tenant.devices.add("web02")
            tenant.machines.add("web02")

    tenant.before = arrive_after_ten_minutes
    result = invoke(
        config_file,
        tenant,
        ["devices", "watch", "web01", "web02", "--interval", "5m", "--timeout", "1h"],
        clock=clock,
    )
    assert result.exit_code == 0, result.output
    assert clock.sleeps == [300, 300]
    assert "pass 1: 1/2 complete" in result.stderr
    assert "every device meets every expectation after 3 pass(es)" in result.stderr


def test_devices_watch_exits_3_when_the_limit_is_reached(config_file, tenant):
    clock = FakeClock()
    result = invoke(
        config_file,
        tenant,
        ["devices", "watch", "ghost", "--interval", "1m", "--max-passes", "2"],
        clock=clock,
    )
    assert result.exit_code == 3, result.output
    assert "reached --max-passes" in result.stderr
    assert clock.sleeps == [60]


def test_devices_watch_rejects_a_bad_interval(config_file, tenant):
    result = invoke(config_file, tenant, ["devices", "watch", "web01", "--interval", "soon"])
    assert result.exit_code == 2


def test_devices_show_passes_a_healthy_device_and_flags_a_missing_one(config_file, tenant):
    healthy = invoke(config_file, tenant, ["devices", "show", "web01"])
    assert healthy.exit_code == 0, healthy.output
    assert "nothing looks wrong" in healthy.stdout
    tenant.devices.add("web02")
    missing = invoke(config_file, tenant, ["devices", "show", "web02", "-o", "json"])
    assert missing.exit_code == 3, missing.output
    findings = json.loads(missing.stdout)["findings"]
    assert {"level": "warn", "message": "no Defender record"} in findings


# entra, xdr, azure, keyvault, logs --------------------------------------------------


def test_app_credentials_exits_3_when_one_is_expiring(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "app-credentials", "-o", "csv"])
    assert result.exit_code == 3, result.output
    header, row = result.stdout.splitlines()
    assert header.startswith("APP,KIND,CREDENTIAL")
    assert row.startswith("billing-api,secret,ci,")


def test_an_empty_ca_policy_list_warns_that_the_token_may_be_why(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "ca-policies"])
    assert result.exit_code == 0, result.output
    assert "may lack Policy.Read.All" in result.stderr


def test_hunt_reads_the_query_from_stdin(config_file, tenant):
    result = invoke(config_file, tenant, ["xdr", "hunt", "-o", "json"], stdin="DeviceInfo | take 1")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"DeviceName": "web01"}]
    hunt = next(r for r in tenant.requests if r.url.endswith("/api/advancedqueries/run"))
    assert json_body(hunt) == {"Query": "DeviceInfo | take 1"}


def test_rbac_resolves_a_upn_through_graph_then_lists_assignments(config_file, tenant):
    result = invoke(config_file, tenant, ["azure", "rbac", "ana@example.com", "-s", SUBSCRIPTION])
    assert result.exit_code == 0, result.output
    assert "Reader" in result.stdout
    assert "this principal" in result.stdout


def test_keyvault_expiry_finds_vaults_through_resource_graph(config_file, tenant):
    result = invoke(config_file, tenant, ["keyvault", "expiry", "--all-vaults", "-o", "json"])
    assert result.exit_code == 3, result.output
    items = json.loads(result.stdout)
    assert [(item["vault"], item["name"], item["days_left"]) for item in items] == [
        ("kv-app", "db", 4)
    ]


def test_logs_query_uses_the_profiles_workspace(config_file, tenant):
    result = invoke(config_file, tenant, ["logs", "query", "Heartbeat", "-o", "csv"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["Computer", "web01"]
    query = next(r for r in tenant.requests if "api.loganalytics.io" in r.url)
    assert urlsplit(query.url).path == f"/v1/workspaces/{WORKSPACE}/query"


# credentials and logging --------------------------------------------------------------


def test_a_client_secret_profile_gets_its_token_from_entra_not_az(config_file, tenant):
    result = invoke(
        config_file,
        tenant,
        ["entra", "token", "graph", "-p", "app", "-o", "json"],
        environ={"AZURE_CLIENT_SECRET": "s3cret"},
    )
    assert result.exit_code == 0, result.output
    login = next(r for r in tenant.requests if "login.microsoftonline.com" in r.url)
    assert form_body(login)["client_secret"] == "s3cret"
    assert "s3cret" not in result.output


def test_a_client_secret_profile_without_the_secret_says_what_to_set(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "token", "graph", "-p", "app"])
    assert result.exit_code == 1
    assert "AZURE_CLIENT_SECRET" in (result.exception.hint or "")


def test_otlp_log_lines_go_to_stderr(config_file, tenant):
    result = invoke(
        config_file, tenant, ["-vv", "--log-format", "otlp", "xdr", "machines", "web01"]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stderr.splitlines() if line.startswith("{")]
    assert lines
    record = json.loads(lines[0])["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert record["severityText"] == "DEBUG"
    assert "eyJ" not in result.stderr


def test_ldo_log_level_from_the_environment_turns_on_logging(config_file, tenant, monkeypatch):
    monkeypatch.setenv("LDO_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LDO_LOG_FORMAT", "OtlpIndented")
    result = invoke(config_file, tenant, ["xdr", "machines", "web01"])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stderr.splitlines() if line.startswith('{"resourceLogs"')]
    assert lines
