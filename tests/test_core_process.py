import subprocess

import pytest

from fakes import FakeRunner
from libre_devops_helpers.core.errors import CommandError
from libre_devops_helpers.core.process import CommandRunner


def runner(respond, **options) -> tuple[CommandRunner, FakeRunner]:
    fake = FakeRunner(respond)
    return CommandRunner("terraform", "/usr/bin/terraform", runner=fake, **options), fake


def test_run_returns_stdout_and_bounds_the_command():
    tool, fake = runner(lambda args: (0, "Terraform v1.9.0\n", ""))
    assert tool.run("version").startswith("Terraform")
    assert fake.calls == [["version"]]
    assert fake.kwargs[0]["timeout"] == CommandRunner.timeout_seconds
    assert fake.kwargs[0]["capture_output"] is True


def test_interactive_commands_are_not_bounded_or_captured():
    tool, fake = runner(lambda args: (0, "", ""))
    tool.run("login", interactive=True)
    assert fake.kwargs[0]["timeout"] is None
    assert fake.kwargs[0]["capture_output"] is False


def test_a_failure_carries_the_cleaned_stderr_and_the_command_label():
    tool, _ = runner(lambda args: (1, "", "\nError: Invalid provider\n\n  on main.tf line 3\n"))
    with pytest.raises(CommandError) as caught:
        tool.run("validate", "-json")
    assert (
        str(caught.value) == "terraform validate failed: Error: Invalid provider on main.tf line 3"
    )


def test_run_json_parses_output_and_reports_non_json():
    tool, _ = runner(lambda args: (0, '{"valid": true}', ""))
    assert tool.run_json("validate", "-json") == {"valid": True}
    tool, _ = runner(lambda args: (0, "not json", ""))
    with pytest.raises(CommandError, match="did not return JSON"):
        tool.run_json("show")


def test_a_timeout_is_reported():
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)

    with pytest.raises(CommandError, match="timed out"):
        CommandRunner("terraform", "/usr/bin/terraform", runner=slow).run("plan")


def test_a_missing_tool_gives_the_install_hint(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    tool = CommandRunner("terraform", install_hint="install it from developer.hashicorp.com")
    with pytest.raises(CommandError, match="'terraform' is not on PATH") as caught:
        tool.run("version")
    assert "hashicorp" in (caught.value.hint or "")


def test_subclasses_supply_their_own_error_type_and_hints():
    class ToolError(CommandError):
        pass

    class Tool(CommandRunner):
        error_type = ToolError

        def hint_for(self, detail: str) -> str | None:
            return "run 'tool login'" if "401" in detail else None

    tool = Tool("tool", "/bin/tool", runner=FakeRunner(lambda args: (1, "", "HTTP 401")))
    with pytest.raises(ToolError) as caught:
        tool.run("status")
    assert caught.value.hint == "run 'tool login'"
