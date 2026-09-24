import io
import sys

import pytest
import typer

from libre_devops_helpers.cli import options
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import InputError


def test_profile_completion_lists_matching_profiles(profiles_config, monkeypatch):
    monkeypatch.setenv(brand.CONFIG_ENV, str(profiles_config))
    assert options.complete_profile("prod") == ["prod", "prod-tenant"]
    assert options.complete_profile("x") == []


def test_profile_completion_is_silent_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv(brand.CONFIG_ENV, str(tmp_path / "missing.toml"))
    assert options.complete_profile("") == []


def test_a_bad_duration_is_a_usage_error():
    assert options.duration(None) is None
    with pytest.raises(typer.BadParameter):
        options.duration("soon")


def test_names_needs_at_least_one(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(InputError, match="no names given"):
        options.names([], None, None)


def test_a_query_comes_from_the_argument_a_file_or_stdin(tmp_path, monkeypatch):
    assert options.read_query("DeviceInfo", None) == "DeviceInfo"
    path = tmp_path / "query.kql"
    path.write_text("Resources | take 1", encoding="utf-8")
    assert options.read_query(None, path) == "Resources | take 1"
    monkeypatch.setattr(sys, "stdin", io.StringIO("SigninLogs"))
    assert options.read_query("-", None) == "SigninLogs"


def test_a_missing_query_or_unreadable_file_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(InputError, match="cannot read"):
        options.read_query(None, tmp_path)  # a directory
    monkeypatch.setattr(sys, "stdin", io.StringIO("   "))
    with pytest.raises(InputError, match="no query given"):
        options.read_query("-", None)


def test_get_runtime_needs_the_root_command_to_have_run():
    bare = typer.Typer()
    bare.command()(lambda: None)
    with pytest.raises(RuntimeError, match="not initialised"):
        options.get_runtime(typer.Context(typer.main.get_command(bare)))
