import json

import pytest

from fakes.http import routes
from fakes.tenant import run
from libre_devops_helpers.core import probe as reach
from libre_devops_helpers.core.network import Route
from libre_devops_helpers.core.probe import Probe


@pytest.fixture
def probes(monkeypatch):
    """Answers each probe from ``outcomes`` by URL (every other URL is fine), and records them."""
    seen: list[str] = []
    outcomes: dict[str, Probe] = {}

    def probe(url, *, expect=range(200, 300), timeout=10.0, **_):
        seen.append(url)
        for fragment, outcome in outcomes.items():
            if fragment in url:
                return outcome
        status = 401 if "securitycenter" in url else 200
        return Probe(
            url, Route(None, "none"), status in set(expect), status, f"HTTP {status}", None, 0.1
        )

    monkeypatch.setattr(reach, "probe", probe)
    return seen, outcomes


def test_every_service_is_asked_and_the_settings_shown(config_file, probes, monkeypatch):
    seen, _ = probes
    monkeypatch.setenv("LDO_PROXY_ADDRESS", "127.0.0.1:3129")
    result = run(config_file, routes({}), ["network", "test"])
    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:3129 (LDO_PROXY_ADDRESS)" in result.stdout
    assert "used as it is (LDO_CA_BUNDLE)" in result.stdout
    # Probed in parallel, so in any order; the table keeps a fixed one.
    assert {url.split("/")[2] for url in seen} >= {
        "login.microsoftonline.com",
        "graph.microsoft.com",
        "management.azure.com",
        "api.securitycenter.microsoft.com",
    }
    rows = [
        line.split("  ")[0]
        for line in result.stdout.splitlines()
        if line.startswith(("Entra", "Microsoft", "Azure", "Defender"))
    ]
    assert rows == [
        "Entra ID sign-in",
        "Microsoft Graph",
        "Azure Resource Manager",
        "Defender for Endpoint",
    ]
    assert "401 without a token is the expected answer" in result.stdout
    assert "reachable" in result.stderr


def test_a_failure_exits_3_with_what_to_try(config_file, probes):
    _, outcomes = probes
    outcomes["graph.microsoft.com"] = Probe(
        "https://graph.microsoft.com/v1.0/",
        Route("http://127.0.0.1:3129", "LDO_PROXY_ADDRESS"),
        False,
        407,
        "the proxy wants a sign-in of its own",
        "run cntlm or Px",
    )
    result = run(config_file, routes({}), ["network", "test", "-o", "json"])
    assert result.exit_code == 3, result.output
    record = json.loads(result.stdout)
    graph = next(item for item in record["endpoints"] if item["name"] == "Microsoft Graph")
    assert (graph["ok"], graph["status"], graph["proxy"]) == (False, 407, "http://127.0.0.1:3129")
    assert record["settings"]["ca_bundle_source"] == "LDO_CA_BUNDLE"
    assert "warning: Microsoft Graph: run cntlm or Px" in result.stderr


def test_a_profiles_cloud_decides_the_endpoints(tmp_path, probes):
    seen, _ = probes
    config = tmp_path / "config.toml"
    config.write_text(
        "[microsoft]\ndefault_profile = 'gov'\n\n[microsoft.profiles.gov]\n"
        "tenant_id = '11111111-1111-1111-1111-111111111111'\ncloud = 'usgov'\n",
        "utf-8",
    )
    result = run(config, routes({}), ["network", "test", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert {url.split("/")[2] for url in seen} >= {"login.microsoftonline.us", "graph.microsoft.us"}


def test_servicenow_instances_and_extra_urls_are_tested_too(config_file, probes):
    seen, _ = probes
    environ = {"SNOW_INSTANCE_URL": "https://dev12345.service-now.com"}
    args = ["network", "test", "--url", "https://intranet.corp.example/health"]
    result = run(config_file, routes({}), args, environ=environ)
    assert result.exit_code == 0, result.output
    assert {"https://dev12345.service-now.com/", "https://intranet.corp.example/health"} <= set(
        seen
    )


def test_an_extra_url_must_be_https(config_file, probes):
    result = run(config_file, routes({}), ["network", "test", "--url", "http://x"])
    assert result.exit_code == 2


def test_a_proxy_password_never_reaches_the_screen_or_json(config_file, probes, monkeypatch):
    _, outcomes = probes
    address = "http://alice:s3cret@127.0.0.1:3129"
    monkeypatch.setenv("LDO_PROXY_ADDRESS", address)
    outcomes["graph.microsoft.com"] = Probe(
        "https://graph.microsoft.com/v1.0/",
        Route(address, "LDO_PROXY_ADDRESS"),
        True,
        200,
        "HTTP 200",
    )
    for output in ("table", "json", "csv", "tsv"):
        result = run(config_file, routes({}), ["network", "test", "-o", output])
        assert "s3cret" not in result.output, output
        assert "alice:***@127.0.0.1:3129" in result.stdout, output
