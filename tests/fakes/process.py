"""A fake subprocess runner for anything the tool runs as a command."""

import subprocess
from collections.abc import Callable
from typing import Any


class FakeRunner:
    """Stands in for subprocess.run. ``respond(args)`` returns (returncode, stdout, stderr)."""

    def __init__(self, respond: Callable[[list[str]], tuple[int, str, str]]) -> None:
        self.respond = respond
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        args = list(cmd[1:])
        self.calls.append(args)
        self.kwargs.append(kwargs)
        code, out, err = self.respond(args)
        return subprocess.CompletedProcess(cmd, code, out, err)
