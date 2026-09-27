import pytest

from fakes.terraform import OUTPUTS, VARIABLES, write_module
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.terraform.sort import Sorting, order_key, sort_file, sort_text, targets


def test_variables_sort_by_name_ignoring_case_with_their_comments():
    text, count, in_order = sort_text(VARIABLES, "variable")
    assert (count, in_order) == (3, False)
    assert text.startswith('variable "Environment" {')
    assert (
        text.index('variable "Environment"')
        < text.index("# The region")
        < text.index('variable "name"')
    )
    assert sort_text(text, "variable") == (text, 3, True)
    assert sort_text(VARIABLES, "output") == (VARIABLES, 0, True)
    assert sorted(["b", "A", "a", "a_b", "ab"], key=order_key) == ["A", "a", "a_b", "ab", "b"]


def test_only_the_blocks_move_and_a_last_block_gains_its_line_break():
    text = 'locals {}\n\n# loose\n\noutput "b" {}\n\noutput "a" {}'
    assert (
        sort_text(text, "output")[0] == 'locals {}\n\n# loose\n\noutput "a" {}\n\noutput "b" {}\n'
    )
    windows = 'output "b" {}\r\noutput "a" {}'
    assert sort_text(windows, "output")[0] == 'output "a" {}\r\noutput "b" {}\r\n'


def test_a_file_is_written_only_when_asked_and_something_moved(tmp_path):
    module = write_module(tmp_path / "module")
    path = module / "outputs.tf"
    assert sort_file(path, ["output"], write=False) == [Sorting(path, "output", 2, False)]
    assert path.read_text(encoding="utf-8") == OUTPUTS
    assert sort_file(path, ["output", "variable"], write=True) == [
        Sorting(path, "output", 2, False, written=True),
        Sorting(path, "variable", 0, True),
    ]
    assert path.read_text(encoding="utf-8").startswith('output "fqdn"')
    assert sort_file(path, ["output"], write=True) == [Sorting(path, "output", 2, True)]
    broken = module / "broken.tf"
    broken.write_text('variable "a" {\n', encoding="utf-8")
    with pytest.raises(InputError, match=r"broken\.tf: its braces"):
        sort_file(broken, ["variable"], write=True)


def test_targets_are_files_named_or_each_folders_variables_and_outputs(tmp_path):
    module = write_module(tmp_path / "module")
    both = ("variable", "output")
    assert targets([module], both, recursive=False) == [
        (module / "variables.tf", ("variable",)),
        (module / "outputs.tf", ("output",)),
    ]
    assert targets([module], ("output",), recursive=True) == [(module / "outputs.tf", ("output",))]
    assert targets([module], ("variable",), recursive=True) == [
        (module / "variables.tf", ("variable",)),
        (module / "examples" / "minimal" / "variables.tf", ("variable",)),
    ]
    main = module / "main.tf"
    main.write_text("", encoding="utf-8")
    assert targets([main], both, recursive=False) == [(main, both)]
    with pytest.raises(InputError, match="is not a file or a folder"):
        targets([module / "missing"], both, recursive=False)
    with pytest.raises(InputError, match=r"no outputs\.tf to sort there") as none:
        targets([module / "examples"], ("output",), recursive=True)
    assert none.value.hint == "name the .tf files to sort"
