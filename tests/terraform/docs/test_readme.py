import pytest

from fakes.terraform import GENERATED, HEADER, FakeTools, write_module
from libre_devops_helpers.core.errors import CommandError, InputError
from libre_devops_helpers.core.process import CommandRunner
from libre_devops_helpers.terraform.docs import BEGIN, END, Readme, document, folders, with_header

MARKERS = f"{BEGIN}\n{END}\n"


def test_the_header_goes_above_the_section_and_the_rest_is_kept():
    readme = f"# Old\n{BEGIN}\ntables\n{END}\nfooter"
    assert with_header(readme, "# New\n\n") == f"# New\n\n{BEGIN}\ntables\n{END}\nfooter\n"
    assert with_header(readme, None) == f"# Old\n\n{BEGIN}\ntables\n{END}\nfooter\n"
    assert with_header("# Mine\n", None) == f"# Mine\n\n{MARKERS}"
    assert with_header("", None) == MARKERS
    assert with_header("", "  \n") == MARKERS
    assert with_header("# A\r\n", "# B\r\n", "\r\n") == f"# B\r\n\r\n{BEGIN}\r\n{END}\r\n"
    with pytest.raises(InputError, match="but no"):
        with_header(f"{BEGIN}\n", "# New")


def tool(tools: FakeTools) -> CommandRunner:
    return CommandRunner("terraform-docs", "/usr/bin/terraform-docs", runner=tools.run)


def test_a_readme_is_written_then_found_up_to_date(tmp_path):
    module = write_module(tmp_path / "module")
    tools = FakeTools("terraform-docs")
    first = document(module, tool=tool(tools), check=False)
    readme = module / "README.md"
    assert first == Readme(module, readme, module / "HEADER.md", "updated")
    assert readme.read_text(encoding="utf-8") == HEADER + "\n" + GENERATED
    assert tools.calls[-1][1:] == [
        "markdown",
        "table",
        "--output-file",
        "README.md",
        "--output-mode",
        "inject",
        str(module),
    ]
    assert document(module, tool=tool(tools), check=True).state == "up to date"
    assert document(module, tool=tool(tools), check=False).state == "up to date"


def test_a_check_changes_nothing_and_a_config_file_is_the_modules_own(tmp_path):
    module = write_module(tmp_path / "module")
    (module / ".terraform-docs.yml").write_text("formatter: markdown table\n", encoding="utf-8")
    before = (module / "README.md").read_text(encoding="utf-8")
    tools = FakeTools("terraform-docs")
    assert document(module, tool=tool(tools), check=True).state == "out of date"
    assert tools.calls == []  # the header differs, so terraform-docs need not say
    (module / "HEADER.md").write_text("# Old title\n", encoding="utf-8")
    assert document(module, tool=tool(tools), check=True).state == "out of date"
    assert tools.calls[-1][1:] == ["--output-check", str(module)]
    assert (module / "README.md").read_text(encoding="utf-8") == before


def test_a_folder_without_a_header_keeps_its_readmes_top(tmp_path):
    module = write_module(tmp_path / "module")
    (module / "HEADER.md").unlink()
    result = document(module, tool=tool(FakeTools()), check=False, readme_name="README.md")
    assert (result.header, result.state) == (None, "updated")
    assert (module / "README.md").read_text(encoding="utf-8") == "# Old title\n\n" + GENERATED
    (module / "README.md").write_text(f"{BEGIN}\n", encoding="utf-8")
    with pytest.raises(InputError, match=r"README\.md: it has"):
        document(module, tool=tool(FakeTools()), check=False)


def test_terraform_docs_failing_for_another_reason_says_so(tmp_path):
    module = write_module(tmp_path / "module")
    (module / "HEADER.md").write_text("# Old title\n", encoding="utf-8")

    def broken(cmd, **_):
        import subprocess

        return subprocess.CompletedProcess(cmd, 1, "", "Error: failed to load module\n")

    with pytest.raises(CommandError, match="failed to load module"):
        document(module, tool=CommandRunner("terraform-docs", "td", runner=broken), check=True)


def test_folders_beneath_are_those_with_a_header_of_their_own(tmp_path):
    module = write_module(tmp_path / "module")
    assert folders([module], recursive=False) == [module]
    assert folders([module], recursive=True) == [module, module / "examples" / "minimal"]
    assert folders([module], recursive=True, header_name="OTHER.md") == [module]
    with pytest.raises(InputError, match="is not a folder"):
        folders([module / "README.md"], recursive=False)
