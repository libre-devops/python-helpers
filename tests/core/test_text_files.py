import os
import stat

import pytest

from libre_devops_helpers.core import text_files
from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.text_files import TextFile, read_text, write_text


def test_a_file_is_written_back_as_it_was_written(tmp_path):
    path = tmp_path / "variables.tf"
    path.write_bytes(b'\xef\xbb\xbfvariable "a" {}\r\n')
    path.chmod(0o640)
    file = read_text(path)
    assert (file.text, file.bom, file.newline) == ('variable "a" {}\r\n', True, "\r\n")
    write_text(file, 'variable "b" {}\r\n')
    assert path.read_bytes() == b'\xef\xbb\xbfvariable "b" {}\r\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640 or os.name == "nt"
    assert [child.name for child in tmp_path.iterdir()] == ["variables.tf"]


def test_a_new_file_is_made_and_plain_utf8_has_no_mark(tmp_path):
    path = tmp_path / "README.md"
    write_text(TextFile(path, ""), "# Title\n")
    assert path.read_bytes() == b"# Title\n"
    assert read_text(path) == TextFile(path, "# Title\n", False, "\n")


def test_what_cannot_be_read_or_written_is_an_input_error(tmp_path, monkeypatch):
    with pytest.raises(InputError, match="cannot read"):
        read_text(tmp_path / "missing.tf")
    binary = tmp_path / "image.tf"
    binary.write_bytes(b"\xff\xfe")
    with pytest.raises(InputError, match="is not UTF-8"):
        read_text(binary)
    with pytest.raises(InputError, match="cannot write in"):
        write_text(TextFile(tmp_path / "no" / "such.tf", ""), "x")

    def refuse(source, target):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(text_files.os, "replace", refuse)
    kept = tmp_path / "kept.tf"
    kept.write_text("before", encoding="utf-8")
    with pytest.raises(InputError, match=r"cannot write .*kept\.tf: Permission denied"):
        write_text(read_text(kept), "after")
    assert kept.read_text(encoding="utf-8") == "before"
    assert sorted(child.name for child in tmp_path.iterdir()) == ["image.tf", "kept.tf"]


def test_an_interrupted_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    def interrupt(source, target):
        raise KeyboardInterrupt

    monkeypatch.setattr(text_files.os, "replace", interrupt)
    path = tmp_path / "a.tf"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        write_text(read_text(path), "y")
    assert [child.name for child in tmp_path.iterdir()] == ["a.tf"]
