import io

import pytest

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.inputs import read_names


def test_arguments_split_on_commas_and_spaces_and_drop_repeats():
    assert read_names(["web01,web02", "db01 WEB01"]) == ["web01", "web02", "db01"]


def test_dash_reads_stdin_in_place():
    stdin = io.StringIO("db01\n# a comment\n\ndb02  # inline\n")
    assert read_names(["web01", "-"], stdin=stdin) == ["web01", "db01", "db02"]


def test_dash_without_stdin_is_an_error():
    with pytest.raises(InputError, match="stdin"):
        read_names(["-"])


def test_a_text_file_holds_one_or_more_names_per_line(tmp_path):
    path = tmp_path / "hosts.txt"
    path.write_text("web01\nweb02,web03\n# retired: web04\n", encoding="utf-8")
    assert read_names(from_file=path) == ["web01", "web02", "web03"]


def test_a_csv_is_read_by_column_header_case_insensitively(tmp_path):
    path = tmp_path / "plan.csv"
    # A byte order mark, as Excel writes, must not end up in the first header.
    path.write_bytes(
        b"\xef\xbb\xbfFQDN,Ring,Notes\n"
        b'web01.example.com,1,"moved, then back"\n'
        b"db01.example.com,2,\n"
    )
    assert read_names(from_file=path, column="fqdn") == ["web01.example.com", "db01.example.com"]


def test_a_single_column_csv_needs_no_column_name(tmp_path):
    path = tmp_path / "groups.csv"
    path.write_text("Group\nMDE Pilot Devices\nLinux Servers\n", encoding="utf-8")
    # Cells are kept whole, so names with spaces survive.
    assert read_names(from_file=path) == ["MDE Pilot Devices", "Linux Servers"]


def test_a_csv_with_several_columns_asks_which(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("FQDN,Ring\nweb01,1\n", encoding="utf-8")
    with pytest.raises(InputError) as caught:
        read_names(from_file=path)
    assert "--column" in (caught.value.hint or "")
    with pytest.raises(InputError, match="no column"):
        read_names(from_file=path, column="hostname")


def test_a_csv_column_can_come_from_stdin():
    stdin = io.StringIO("name,os\nweb01,linux\nweb02,linux\n")
    assert read_names(["-"], stdin=stdin, column="name") == ["web01", "web02"]
