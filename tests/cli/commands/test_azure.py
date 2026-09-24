import json

from fakes.http import routes
from fakes.ids import OTHER_SUBSCRIPTION, SUBSCRIPTION, TENANT
from fakes.tenant import invoke, run

SECURITY = f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Security"
SUBSCRIPTIONS = (
    200,
    {"value": [{"subscriptionId": SUBSCRIPTION, "displayName": "prod", "tenantId": TENANT}]},
)


def assessment(name: str, severity: str, status: str = "Unhealthy") -> dict:
    return {
        "id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.Compute"
        f"/virtualMachines/vm1/providers/Microsoft.Security/assessments/{name}",
        "properties": {
            "displayName": name,
            "status": {"code": status},
            "metadata": {"severity": severity},
        },
    }


def test_rbac_resolves_a_upn_through_graph_then_lists_assignments(config_file, tenant):
    result = invoke(config_file, tenant, ["azure", "rbac", "ana@example.com", "-s", SUBSCRIPTION])
    assert result.exit_code == 0, result.output
    assert "Reader" in result.stdout
    assert "this principal" in result.stdout


def test_subscriptions_lists_those_in_the_profiles_tenant(config_file):
    result = run(config_file, routes({"/subscriptions": SUBSCRIPTIONS}), ["azure", "subscriptions"])
    assert result.exit_code == 0, result.output
    assert "prod" in result.stdout
    assert SUBSCRIPTION in result.stdout


def test_resource_graph_reads_the_query_from_stdin_and_counts_rows(config_file):
    reply = (200, {"data": [{"name": "vm1", "type": "microsoft.compute/virtualmachines"}]})
    handler = routes({"/providers/Microsoft.ResourceGraph/resources": reply})
    result = run(
        config_file, handler, ["azure", "resource-graph", "-", "-o", "csv"], stdin="Resources"
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[1] == "vm1,microsoft.compute/virtualmachines"
    assert "1 row(s)" in result.stderr


def test_secure_score_covers_every_subscription_and_warns_about_missing_ones(config_file):
    other = f"/subscriptions/{OTHER_SUBSCRIPTION}/providers/Microsoft.Security"
    handler = routes(
        {
            f"{SECURITY}/secureScores/ascScore": (
                200,
                {"properties": {"score": {"current": 12.5, "max": 40, "percentage": 0.3125}}},
            ),
            f"{other}/secureScores/ascScore": (404, {"error": {"code": "NotFound"}}),
            f"{SECURITY}/secureScoreControls": (
                200,
                {
                    "value": [
                        {"properties": {"displayName": "MFA", "score": {"current": 0, "max": 10}}}
                    ]
                },
            ),
        }
    )
    args = ["azure", "secure-score", "-s", SUBSCRIPTION, "-s", OTHER_SUBSCRIPTION, "--controls"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    assert "12.5" in result.stdout
    assert "31%" in result.stdout
    assert "MFA" in result.stdout
    assert "1 subscription(s) have no secure score" in result.stderr


def test_recommendations_filter_by_severity_across_subscriptions(config_file):
    handler = routes(
        {
            "/subscriptions": SUBSCRIPTIONS,
            f"{SECURITY}/assessments": (
                200,
                {"value": [assessment("Patch it", "High"), assessment("Tidy it", "Low")]},
            ),
        }
    )
    result = run(config_file, handler, ["azure", "recommendations", "--severity", "HIGH"])
    assert result.exit_code == 0, result.output
    assert "Patch it" in result.stdout
    assert "Tidy it" not in result.stdout
    assert "1 result(s)" in result.stderr


def test_recommendations_reject_an_unknown_severity(config_file):
    result = run(config_file, routes({}), ["azure", "recommendations", "--severity", "urgent"])
    assert result.exit_code == 2
    assert "--severity must be high, medium or low" in result.output


def test_defender_plans_show_which_are_on(config_file):
    plans = {
        "value": [
            {"name": "VirtualMachines", "properties": {"pricingTier": "Standard", "subPlan": "P2"}},
            {"name": "Api", "properties": {"pricingTier": "Free", "deprecated": True}},
        ]
    }
    handler = routes({f"{SECURITY}/pricings": (200, plans)})
    result = run(
        config_file, handler, ["azure", "defender-plans", "-s", SUBSCRIPTION, "-o", "json"]
    )
    assert result.exit_code == 0, result.output
    records = json.loads(result.stdout)
    assert [(r["name"], r["subscriptionId"]) for r in records] == [
        ("Api", SUBSCRIPTION),
        ("VirtualMachines", SUBSCRIPTION),
    ]
    table = run(config_file, handler, ["azure", "defender-plans", "-s", SUBSCRIPTION])
    assert "deprecated" in table.stdout
