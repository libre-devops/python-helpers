import json

from fakes.tenant import run, usage_error
from fakes.terraform import GENERATED, HEADER, FakeTools, write_module
from libre_devops_helpers.core.errors import CommandError, InputError


def terraform(config_file, *args, tools=None):
    tools = tools or FakeTools()
    return run(config_file, None, ["terraform", *args], tools=tools), tools


def test_sort_puts_a_folders_variables_and_outputs_in_order_then_formats_it(
    config_file, tmp_path, monkeypatch
):
    module = write_module(tmp_path / "module")
    monkeypatch.chdir(module)
    tools = FakeTools("tofu")
    tools.formatted = ["variables.tf"]
    result, _ = terraform(config_file, "sort", "-o", "json", tools=tools)
    assert result.exit_code == 0, result.output
    assert [
        (row["file"], row["blocks"], row["count"], row["state"])
        for row in json.loads(result.stdout)
    ] == [
        ("variables.tf", "variables", 3, "sorted"),
        ("outputs.tf", "outputs", 2, "sorted"),
    ]
    assert (
        (module / "variables.tf").read_text(encoding="utf-8").startswith('variable "Environment"')
    )
    assert "sorted 2 of 2; the rest were in order" in result.stderr
    assert "tofu fmt formatted 1 file(s)" in result.stderr
    assert tools.calls == [["/usr/bin/tofu", "fmt", "."]]


def test_sort_can_take_only_the_inputs_or_outputs_and_the_folders_beneath(config_file, tmp_path):
    module = write_module(tmp_path / "module")
    inputs, tools = terraform(
        config_file, "sort", str(module), "--inputs", "-r", "--no-fmt", "-o", "csv"
    )
    assert inputs.exit_code == 0, inputs.output
    assert [line.split(",")[1:] for line in inputs.stdout.splitlines()[1:]] == [
        ["variables", "3", "sorted"],
        ["variables", "2", "sorted"],
    ]
    assert tools.calls == []
    outputs, _ = terraform(config_file, "sort", str(module), "--outputs", "-o", "csv")
    assert [line.split(",")[1:] for line in outputs.stdout.splitlines()[1:]] == [
        ["outputs", "2", "sorted"]
    ]
    assert "terraform fmt not run: neither terraform nor tofu is on PATH" in outputs.stderr
    assert (
        '"z"'
        in (module / ".terraform" / "modules" / "other" / "variables.tf")
        .read_text(encoding="utf-8")
        .split("\n")[0]
    )


def test_sort_check_changes_nothing_and_exits_3_when_out_of_order(config_file, tmp_path):
    module = write_module(tmp_path / "module")
    before = (module / "outputs.tf").read_text(encoding="utf-8")
    check, tools = terraform(
        config_file, "sort", str(module / "outputs.tf"), "--check", "-o", "csv"
    )
    assert check.exit_code == 3, check.output
    assert check.stdout.splitlines()[1:] == [
        f"{module / 'outputs.tf'},variables,0,in order",
        f"{module / 'outputs.tf'},outputs,2,out of order",
    ]
    assert "1 of 2 not in order: run without --check" in check.stderr
    assert (module / "outputs.tf").read_text(encoding="utf-8") == before
    assert tools.calls == []
    terraform(config_file, "sort", str(module), "--no-fmt")
    again, _ = terraform(config_file, "sort", str(module), "--check")
    assert again.exit_code == 0, again.output
    assert "0 of 2 not in order" in again.stderr


def test_sort_says_what_it_cannot_sort(config_file, tmp_path):
    missing, _ = terraform(config_file, "sort", str(tmp_path / "nowhere"))
    assert isinstance(missing.exception, InputError)
    assert "is not a file or a folder" in str(missing.exception)


def test_docs_writes_each_readme_from_its_header_and_terraform_docs(config_file, tmp_path):
    module = write_module(tmp_path / "module")
    tools = FakeTools("terraform-docs")
    result, _ = terraform(config_file, "docs", str(module), "-r", "-o", "json", tools=tools)
    assert result.exit_code == 0, result.output
    assert [(row["header"] is not None, row["state"]) for row in json.loads(result.stdout)] == [
        (True, "updated"),
        (True, "updated"),
    ]
    assert (module / "README.md").read_text(encoding="utf-8") == HEADER + "\n" + GENERATED
    example = module / "examples" / "minimal" / "README.md"
    assert example.read_text(encoding="utf-8") == "# The minimal example\n\n" + GENERATED
    check, _ = terraform(
        config_file, "docs", str(module), "-r", "--check", "-o", "csv", tools=tools
    )
    assert check.exit_code == 0, check.output
    assert check.stdout.splitlines()[1].endswith(",HEADER.md,up to date")
    (module / "HEADER.md").write_text("# Changed\n", encoding="utf-8")
    stale, _ = terraform(config_file, "docs", str(module), "--check", tools=tools)
    assert stale.exit_code == 3, stale.output
    assert "1 of 1 out of date: run without --check" in stale.stderr


def test_docs_needs_terraform_docs_and_plain_file_names(config_file, tmp_path):
    module = write_module(tmp_path / "module")
    missing, _ = terraform(config_file, "docs", str(module))
    assert isinstance(missing.exception, CommandError)
    assert str(missing.exception) == "terraform-docs is not on PATH"
    assert "terraform-docs.io" in missing.exception.hint
    for option in ("--header", "--readme"):
        bad, _ = terraform(config_file, "docs", str(module), option, "../x.md")
        assert bad.exit_code == 2
        assert "give a file name" in usage_error(bad)
