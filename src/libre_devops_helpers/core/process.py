"""Run an external command line tool: checked exit codes, a timeout, readable errors.

Vendor layers build on ``CommandRunner`` for their own tools (the Azure CLI today),
supplying how that tool's errors read and what to suggest. Output is returned to the
caller but never logged, because it can hold a token.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from libre_devops_helpers.core.errors import CommandError

log = logging.getLogger(__name__)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class CommandRunner:
    """Runs one executable, found on ``PATH`` by ``name`` unless ``executable`` is given.

    ``runner`` defaults to ``subprocess.run``; tests pass a fake so nothing real runs.
    Subclasses override ``clean_stderr`` and ``hint_for`` for their tool, and
    ``error_type`` for a more specific error.
    """

    error_type: type[CommandError] = CommandError
    # Non-interactive commands are bounded. Interactive ones wait on a person, so are not.
    timeout_seconds = 120

    def __init__(
        self,
        name: str,
        executable: str | None = None,
        *,
        install_hint: str | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self.name = name
        self._executable = executable
        self._install_hint = install_hint
        self._runner = runner

    @property
    def executable(self) -> str:
        """Path to the tool, resolved on first use so importing never requires it."""
        if self._executable is None:
            found = shutil.which(self.name)
            if found is None:
                raise self.error_type(f"'{self.name}' is not on PATH", hint=self._install_hint)
            self._executable = found
        return self._executable

    def run(
        self, *args: str, interactive: bool = False, env: Mapping[str, str] | None = None
    ) -> str:
        """Run the tool with ``args`` and return stdout. Raises on a non-zero exit.

        ``interactive`` connects the terminal instead of capturing output.
        """
        label = " ".join(
            [self.name, *itertools.takewhile(lambda arg: not arg.startswith("-"), args)]
        )
        log.debug("running %s", " ".join([self.name, *args]))
        try:
            result = self._runner(
                [self.executable, *args],
                capture_output=not interactive,
                text=True,
                env={**os.environ, **env} if env else None,
                timeout=None if interactive else self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise self.error_type(f"{label} timed out after {self.timeout_seconds}s") from None
        except OSError as exc:
            raise self.error_type(f"cannot run {label}: {exc}") from None
        if result.returncode != 0:
            detail = self.clean_stderr(result.stderr) or f"exit code {result.returncode}"
            raise self.error_type(f"{label} failed: {detail}", hint=self.hint_for(detail))
        return result.stdout or ""

    def run_json(self, *args: str) -> Any:
        """Run the tool and parse its stdout as JSON (None for no output)."""
        out = self.run(*args).strip()
        if not out:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            raise self.error_type(f"{self.name} {' '.join(args[:2])} did not return JSON") from None

    def clean_stderr(self, stderr: str | None) -> str:
        """The error message from stderr, on one line."""
        return " ".join(line.strip() for line in (stderr or "").splitlines() if line.strip())[:1000]

    def hint_for(self, detail: str) -> str | None:
        """A next step for a failed command, when the message points to one."""
        return None
