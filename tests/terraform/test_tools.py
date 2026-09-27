from pathlib import Path

import pytest

from fakes.terraform import FakeTools
from libre_devops_helpers.core.errors import CommandError
from libre_devops_helpers.terraform.tools import (
    TERRAFORM_DOCS_HINT,
    format_code,
    formatter,
    terraform_docs,
)


def test_terraform_formats_and_tofu_stands_in_when_it_is_missing():
    both = FakeTools("terraform", "tofu")
    assert formatter(which=both.find, runner=both.run).name == "terraform"
    tofu = FakeTools("tofu")
    tool = formatter(which=tofu.find, runner=tofu.run)
    assert tool.name == "tofu"
    tofu.formatted = ["variables.tf"]
    assert format_code(tool, [Path("a"), Path("b.tf")], recursive=False) == [
        "variables.tf",
        "variables.tf",
    ]
    assert format_code(tool, [Path("a")], recursive=True) == ["variables.tf"]
    assert [call[1:] for call in tofu.calls] == [
        ["fmt", "a"],
        ["fmt", "b.tf"],
        ["fmt", "-recursive", "a"],
    ]
    assert formatter(which=FakeTools().find) is None


def test_terraform_docs_must_be_on_path():
    tools = FakeTools("terraform-docs")
    assert terraform_docs(which=tools.find, runner=tools.run).name == "terraform-docs"
    with pytest.raises(CommandError) as missing:
        terraform_docs(which=FakeTools().find)
    assert missing.value.hint == TERRAFORM_DOCS_HINT
