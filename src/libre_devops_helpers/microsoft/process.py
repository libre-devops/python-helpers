"""The Azure CLI as a subprocess: JSON output and ``az``'s own error shapes and hints.

Shared by ``microsoft.auth.AzureCliCredential`` (tokens) and ``microsoft.azcli``
(accounts and context switching). The subprocess handling itself is core's
``CommandRunner``; this adds what is particular to ``az``.
"""

from __future__ import annotations

from typing import Any

from libre_devops_helpers.core.errors import CommandError
from libre_devops_helpers.core.process import CommandRunner, Runner

# az prefixes an unexpected failure with this line, then dumps a Python traceback.
_UNEXPECTED = "The command failed with an unexpected error. Here is the traceback:"
INSTALL_HINT = "install it: https://learn.microsoft.com/cli/azure/install-azure-cli"


class AzCliError(CommandError):
    """The Azure CLI is missing, or a command it ran failed."""


class AzureCliRunner(CommandRunner):
    """Runs ``az`` commands with JSON output and checks their exit codes."""

    error_type = AzCliError

    def __init__(self, executable: str | None = None, *, runner: Runner | None = None) -> None:
        options = {"runner": runner} if runner is not None else {}
        super().__init__("az", executable, install_hint=INSTALL_HINT, **options)

    def run_json(self, *args: str) -> Any:
        """Run ``az`` with JSON output and return the parsed value (None for no output)."""
        return super().run_json(*args, "--output", "json", "--only-show-errors")

    def clean_stderr(self, stderr: str | None) -> str:
        return clean_stderr(stderr)

    def hint_for(self, detail: str) -> str | None:
        return hint_for(detail)


def clean_stderr(stderr: str | None) -> str:
    """The error message from ``az`` stderr, without any Python traceback after it."""
    lines: list[str] = []
    for raw in (stderr or "").splitlines():
        line = raw.strip()
        if line.startswith("Traceback (most recent call last)"):
            break
        line = line.removeprefix("ERROR: ")
        if line and line != _UNEXPECTED:
            lines.append(line)
    return " ".join(lines)[:1000]


def signed_out(message: str) -> bool:
    """True when an ``az`` error means there is no usable session."""
    return "az login" in message


def hint_for(detail: str) -> str | None:
    """A next step for a failed ``az`` command, when the message points to one."""
    if "Unable to get authority configuration" in detail:
        return (
            "no such tenant: check the tenant id (for a profile, its tenant_id in the config file)"
        )
    if signed_out(detail) or "AADSTS" in detail:
        return "the Azure CLI session is missing or expired; sign in again (az login --tenant <id>)"
    return None
