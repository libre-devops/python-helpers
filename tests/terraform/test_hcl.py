import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.terraform.hcl import Piece, split

MODULE = """\
# Loose note, a blank line above the block, so it stays where it is.

// Documents the block below it, so moves with it.
/* And so
   does this. */
variable "a" {
  description = <<-EOT
  A brace on a line of its own:
}
  EOT
  default = "${ {x = "}"}["x"] }$${not a template}"
}
variable b {}
locals {
  map = { "}" = "{" } # a { in a comment
}
"""


def test_a_file_splits_into_its_blocks_and_what_lies_between_them():
    pieces = split(MODULE)
    assert "".join(piece.text for piece in pieces) == MODULE
    assert [(piece.kind, piece.name) for piece in pieces] == [
        (None, None),
        ("variable", "a"),
        ("variable", "b"),
        ("locals", None),
    ]
    assert pieces[0] == Piece(
        "# Loose note, a blank line above the block, so it stays where it is.\n\n"
    )
    assert pieces[1].text.startswith("// Documents the block below it")
    assert pieces[1].text.endswith('$${not a template}"\n}\n')


def test_a_label_can_be_escaped_and_a_file_can_end_without_a_line_break():
    pieces = split('output "a\\"b" {\n  value = 1\n}')
    assert (pieces[0].kind, pieces[0].name, pieces[0].text) == (
        "output",
        'a\\"b',
        'output "a\\"b" {\n  value = 1\n}',
    )
    assert split("") == []


@pytest.mark.parametrize(
    "text",
    [
        'variable "a" {\n',
        'variable "a" {\n}\n}\n',
        'variable "a" {\n  default = "open\n}\n',
        "/* never closed\n",
        'variable "a" {\n  description = <<EOT\nno end\n}\n',
    ],
    ids=["open", "extra", "string", "comment", "heredoc"],
)
def test_braces_strings_comments_and_heredocs_must_close(text):
    with pytest.raises(InputError, match="do not all close"):
        split(text)
