import json

from fakes.http import routes
from fakes.ids import SUBSCRIPTION, TENANT
from fakes.logicapps import ARM_RESOURCE, CODE_VIEW, write
from fakes.tenant import run

GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-soc"

WORKFLOWS = f"{GROUP}/providers/Microsoft.Logic/workflows"


def test_export_writes_one_code_view_file_per_workflow(config_file, tmp_path):
    handler = routes(
        {
            WORKFLOWS: (200, {"value": [{"name": "logic-arm"}, {"name": "other"}]}),
            f"{WORKFLOWS}/logic-arm": (200, ARM_RESOURCE),
        }
    )
    out = tmp_path / "raw"
    args = [
        "logicapp",
        "export",
        "-g",
        "rg-soc",
        "--out",
        str(out),
        "--name",
        "logic-arm",
        "-s",
        SUBSCRIPTION,
    ]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    written = json.loads((out / "logic-arm.json").read_text())
    assert set(written) == {"definition", "parameters"}
    assert written["definition"] == ARM_RESOURCE["properties"]["definition"]
    assert not (out / "other.json").exists()
    arm = run(config_file, handler, [*args, "--shape", "arm"])
    assert arm.exit_code == 0, arm.output
    assert json.loads((out / "logic-arm.json").read_text())["name"] == "logic-arm"


def test_export_finds_the_subscription_when_the_profile_sees_just_one(config_file, tmp_path):
    subscriptions = (
        200,
        {"value": [{"subscriptionId": SUBSCRIPTION, "displayName": "prod", "tenantId": TENANT}]},
    )
    handler = routes({"/subscriptions": subscriptions, WORKFLOWS: (200, {"value": []})})
    result = run(
        config_file, handler, ["logicapp", "export", "-g", "rg-soc", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "no Logic App workflows matched" in result.stderr


def test_validate_reports_the_providers_verdict(config_file, tmp_path):
    source = write(tmp_path, "router.json", CODE_VIEW)
    validate = f"{GROUP}/providers/Microsoft.Logic/locations/uksouth/workflows/router/validate"
    accepted = routes({GROUP: (200, {"location": "uksouth"}), validate: (200, b"")})
    args = ["logicapp", "validate", str(source), "-g", "rg-soc", "-s", SUBSCRIPTION]
    result = run(config_file, accepted, args)
    assert result.exit_code == 0, result.output
    assert "accepted" in result.stdout
    rejected = routes(
        {
            validate: (
                400,
                {"error": {"code": "InvalidTemplate", "message": "The value is not provided"}},
            )
        }
    )
    refused = run(config_file, rejected, [*args, "--location", "uksouth", "-o", "json"])
    assert refused.exit_code == 3
    assert json.loads(refused.stdout)["valid"] is False
