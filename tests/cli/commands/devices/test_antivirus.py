import json

from fakes.http import routes
from fakes.tenant import run
from libre_devops_helpers.core.errors import InputError

AV_REPLY = {
    "schema": [{"name": "DeviceName"}, {"name": "AvSignatureVersion"}],
    "results": [
        {
            "DeviceId": "m1",
            "DeviceName": "web01.corp.example.com",
            "OSPlatform": "Windows11",
            "Reported": "2026-09-24T08:00:00Z",
            "AvSignatureVersion": "1.419.120.0",
            "AvEngineVersion": "1.1.24080.9",
            "AvPlatformVersion": "4.18.24080.9",
            "AvMode": "0",
            "SignatureUpToDate": True,
        }
    ],
}


def test_av_signature_goes_through_graph_hunting(config_file):
    seen = []

    def hunting(request):
        seen.append(json.loads(request.body))
        return (200, AV_REPLY)

    handler = routes({"/v1.0/security/runHuntingQuery": hunting})
    result = run(config_file, handler, ["device", "av-signature", "web01", "-o", "csv"])
    assert result.exit_code == 0, result.output
    header, line = result.stdout.splitlines()
    assert header == "DEVICE,MACHINE,OS,SIGNATURE,ENGINE,PLATFORM,MODE,UP TO DATE,REPORTED"
    assert line.startswith(
        "web01,web01.corp.example.com,Windows11,1.419.120.0,1.1.24080.9,4.18.24080.9,active,yes,"
    )
    assert "DeviceTvmInfoGathering" in seen[0]["Query"]
    assert "Timespan" not in seen[0]
    assert "1 found" in result.stderr


def test_av_signature_exits_3_for_a_missing_or_old_device(config_file):
    handler = routes({"/v1.0/security/runHuntingQuery": (200, AV_REPLY)})
    args = ["devices", "av-signature", "web01,ghost", "--at-least", "1.419.200.0", "-o", "json"]
    result = run(config_file, handler, args)
    assert result.exit_code == 3, result.output
    web01, ghost = json.loads(result.stdout)
    assert (web01["signature_version"], web01["older_than_minimum"]) == ("1.419.120.0", True)
    assert (ghost["found"], ghost["older_than_minimum"]) == (False, None)
    assert "1 not found, 1 older than 1.419.200.0" in result.stderr


def test_av_signature_with_endpoint_uses_the_defender_api(config_file):
    endpoint = {"Schema": AV_REPLY["schema"], "Results": AV_REPLY["results"]}
    handler = routes({"/api/advancedqueries/run": (200, endpoint)})
    result = run(config_file, handler, ["devices", "av-signature", "web01", "--endpoint"])
    assert result.exit_code == 0, result.output
    assert "1.419.120.0" in result.stdout


def test_av_signature_can_print_its_query_or_refuse_a_bad_version(config_file):
    shown = run(config_file, routes({}), ["devices", "av-signature", "web01", "--show-query"])
    assert shown.exit_code == 0, shown.output
    assert shown.stdout.startswith('let wanted = dynamic(["web01"]);')
    bad = run(config_file, routes({}), ["devices", "av-signature", "web01", "--at-least", "new"])
    assert isinstance(bad.exception, InputError)
