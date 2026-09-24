import io
import json
import re

import pytest

from fakes.tenant import runner
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.commands import pretty
from libre_devops_helpers.core.errors import InputError

ANSI = re.compile(r"\x1b\[[0-9;]*m")
DOCUMENT = {"value": [{"id": "1", "displayName": "Ana", "tags": []}], "count": 1, "city": "Zürich"}


def test_json_from_stdin_is_indented_and_plain_when_piped():
    result = runner.invoke(app, ["json"], input=json.dumps(DOCUMENT))
    assert result.exit_code == 0, result.output
    assert result.stdout == json.dumps(DOCUMENT, indent=2, ensure_ascii=False) + "\n"
    assert "\x1b[" not in result.stdout


def test_colour_can_be_forced_and_changes_nothing_but_colour():
    result = runner.invoke(app, ["json", "--colour", "--sort-keys"], input=json.dumps(DOCUMENT))
    assert "\x1b[" in result.stdout
    expected = json.dumps(DOCUMENT, indent=2, sort_keys=True, ensure_ascii=False)
    assert ANSI.sub("", result.stdout) == expected + "\n"


def test_json_lines_come_out_one_document_each_and_compact():
    lines = '{"a": 1}\n\n{"b": [1, 2]}\n'
    result = runner.invoke(app, ["json", "--compact"], input=lines)
    assert result.stdout.splitlines() == ['{"a":1}', '{"b":[1,2]}']


def test_a_file_is_read_and_its_indent_chosen(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"a": {"b": 1}}), encoding="utf-8")
    result = runner.invoke(app, ["json", str(path), "--indent", "4"])
    assert result.stdout == json.dumps({"a": {"b": 1}}, indent=4) + "\n"
    missing = runner.invoke(app, ["json", str(tmp_path / "nope.json")])
    assert isinstance(missing.exception, InputError)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"a": 1,,}', "not JSON: Expecting property name enclosed in double quotes at line 1"),
        ('{"a": 1}\nnot json\n', "not JSON: Extra data at line 2"),
        ("   \n", "the input is empty"),
    ],
)
def test_bad_input_says_where_it_broke(text, message):
    result = runner.invoke(app, ["json"], input=text)
    assert isinstance(result.exception, InputError)
    assert str(result.exception).startswith(message)


def test_nothing_piped_on_a_terminal_explains_how_to_use_it(monkeypatch):
    terminal = io.StringIO()
    terminal.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", terminal)
    with pytest.raises(InputError) as caught:
        pretty._read(None)
    assert "| ldo json" in (caught.value.hint or "")


def test_yaml_reads_back_as_the_json_it_came_from():
    import yaml

    result = runner.invoke(app, ["json", "--yaml"], input=json.dumps(DOCUMENT))
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.stdout) == DOCUMENT
    assert "\x1b[" not in result.stdout


def test_yaml_documents_from_json_lines_are_separated_and_can_be_coloured():
    import yaml

    result = runner.invoke(app, ["json", "--yaml", "--sort-keys"], input='{"b":1,"a":2}\n{"c":3}\n')
    assert result.stdout == "a: 2\nb: 1\n---\nc: 3\n"
    assert list(yaml.safe_load_all(result.stdout)) == [{"a": 2, "b": 1}, {"c": 3}]
    coloured = runner.invoke(app, ["json", "--yaml", "--colour"], input=json.dumps(DOCUMENT))
    assert "\x1b[" in coloured.stdout
    assert yaml.safe_load(ANSI.sub("", coloured.stdout)) == DOCUMENT


def test_yaml_has_no_compact_form():
    result = runner.invoke(app, ["json", "--yaml", "--compact"], input="{}")
    assert isinstance(result.exception, InputError)
