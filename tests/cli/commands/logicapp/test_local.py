import copy
import json

from fakes.http import routes
from fakes.logicapps import ARM_RESOURCE, BARE, CODE_VIEW, REFERENCES, dispatcher, write
from fakes.tenant import run


def offline(config_file, args):
    return run(config_file, routes({}), ["logicapp", *args])


def test_check_passes_a_complete_definition_and_gates_on_errors(config_file, tmp_path):
    good = write(tmp_path, "router.json", CODE_VIEW)
    result = offline(config_file, ["check", str(good), "--connection", "servicenow"])
    assert result.exit_code == 0, result.output
    assert "1 definition(s): 0 error(s), 0 warning(s)" in result.stderr
    broken = copy.deepcopy(CODE_VIEW)
    del broken["parameters"]["ticket_prefix"]
    bad = write(tmp_path, "broken.json", broken)
    failed = offline(config_file, ["check", str(bad), "--connection", "servicenow", "-o", "json"])
    assert failed.exit_code == 3
    assert [item["rule"] for item in json.loads(failed.stdout)] == ["parameter-has-no-value"]


def test_check_takes_folders_and_strict_fails_on_warnings(config_file, tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    write(folder, "router.json", CODE_VIEW)
    write(folder, "handler.json.tftpl", json.dumps(BARE).replace('"x"', '"${table}"'))
    write(folder, "notes.txt", "ignored")
    result = offline(config_file, ["check", str(folder), "--supplied", "ticket_prefix"])
    assert "2 definition(s)" in result.stderr
    assert "connections-unwired" in result.stdout  # a warning only
    assert result.exit_code == 0, result.output
    strict = offline(config_file, ["check", str(folder), "--supplied", "ticket_prefix", "--strict"])
    assert strict.exit_code == 3


def test_an_empty_folder_is_an_error(config_file, tmp_path):
    result = offline(config_file, ["check", str(tmp_path)])
    assert "no definition files found" in str(result.exception)


def test_params_lists_every_declaration_or_only_the_unsatisfied(config_file, tmp_path):
    bare = write(tmp_path, "bare.json", BARE)
    result = offline(config_file, ["params", str(bare), "-o", "json"])
    assert [(item["name"], item["satisfied"]) for item in json.loads(result.stdout)] == [
        ("ticket_prefix", False)
    ]
    router = write(tmp_path, "router.json", CODE_VIEW)
    unsatisfied = offline(config_file, ["params", str(router), "--unsatisfied", "-o", "csv"])
    assert len(unsatisfied.stdout.splitlines()) == 1  # the header only


def test_references_exit_3_when_a_key_is_unwired(config_file, tmp_path):
    wired = write(tmp_path, "wired.json", REFERENCES)
    assert offline(config_file, ["references", str(wired)]).exit_code == 0
    mismatched = copy.deepcopy(REFERENCES)
    value = mismatched["parameters"]["$connections"]["value"]
    value["service-now"] = value.pop("servicenow")
    unwired = write(tmp_path, "unwired.json", mismatched)
    result = offline(config_file, ["references", str(unwired), "--unwired", "-o", "json"])
    assert result.exit_code == 3
    assert [item["key"] for item in json.loads(result.stdout)] == ["servicenow"]


def test_connections_show_managed_identity(config_file, tmp_path):
    router = write(tmp_path, "router.json", CODE_VIEW)
    result = offline(config_file, ["connections", str(router), "-o", "json"])
    found = {item["key"]: item["managed_identity"] for item in json.loads(result.stdout)}
    assert found == {"servicenow": True, "azuresentinel": False}


def test_order_lists_the_tiers(config_file, tmp_path):
    for name, target in (("router", "dispatcher"), ("dispatcher", "handler"), ("handler", None)):
        write(tmp_path, f"{name}.json", dispatcher(target))
    result = offline(config_file, ["order", str(tmp_path), "-o", "csv"])
    assert result.stdout.splitlines() == [
        "TIER,WORKFLOW,DEPENDS ON",
        "0,handler,",
        "1,dispatcher,handler",
        "2,router,dispatcher",
    ]


def test_diff_exits_3_when_the_definitions_differ(config_file, tmp_path):
    left = write(tmp_path, "left.json", CODE_VIEW)
    changed = copy.deepcopy(CODE_VIEW)
    changed["definition"]["actions"]["Compose"]["inputs"] = "other"
    right = write(tmp_path, "right.json", changed)
    assert offline(config_file, ["diff", str(left), str(left)]).exit_code == 0
    result = offline(config_file, ["diff", str(left), str(right)])
    assert result.exit_code == 3
    assert "definition.actions.Compose.inputs" in result.stdout


def test_defaults_print_or_write_the_standalone_definition(config_file, tmp_path):
    router = write(tmp_path, "router.json", CODE_VIEW)
    printed = offline(config_file, ["defaults", str(router)])
    assert json.loads(printed.stdout)["parameters"]["ticket_prefix"]["defaultValue"] == "SIR"
    assert "added 3 default(s)" in printed.stderr
    out = tmp_path / "portable.json"
    offline(config_file, ["defaults", str(router), "--out", str(out)])
    assert json.loads(out.read_text())["parameters"]["retry_count"]["defaultValue"] == 3


def test_rewrite_applies_replacements_in_order(config_file, tmp_path):
    source = write(tmp_path, "arm.json", ARM_RESOURCE)
    args = [
        "rewrite",
        str(source),
        "--replace",
        "rg/providers=rg-new/providers",
        "--replace",
        "SIR=INC",
    ]
    result = offline(config_file, args)
    assert result.exit_code == 0, result.output
    assert "/resourceGroups/rg-new/providers" in result.stdout
    assert '"INC"' in result.stdout
    bad = offline(config_file, ["rewrite", str(source), "--replace", "no-equals-sign"])
    assert bad.exit_code == 2
