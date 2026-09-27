"""The command line tools run on a module: terraform (or OpenTofu's tofu) to format it, and
terraform-docs to write its README's generated section. Neither ships with this package:
each is found on PATH, and one that is missing says how to install it."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from libre_devops_helpers.core.errors import CommandError
from libre_devops_helpers.core.process import CommandRunner, Runner

Finder = Callable[[str], "str | None"]
# terraform first, as the module's own tool; OpenTofu's formats the same.
FORMATTERS = ("terraform", "tofu")
TERRAFORM_DOCS_HINT = "install terraform-docs: https://terraform-docs.io/user-guide/installation/"


def formatter(
    *, which: Finder = shutil.which, runner: Runner = subprocess.run
) -> CommandRunner | None:
    """terraform, else tofu, as found on PATH; None when neither is there."""
    for name in FORMATTERS:
        found = which(name)
        if found:
            return CommandRunner(name, found, runner=runner)
    return None


def format_code(tool: CommandRunner, targets: Sequence[Path], *, recursive: bool) -> list[str]:
    """Format each of ``targets`` (a folder, or a file) with ``tool fmt``, and the folders
    beneath one too when ``recursive``: the files it changed."""
    changed: list[str] = []
    for target in targets:
        args = ["fmt", "-recursive", str(target)] if recursive else ["fmt", str(target)]
        changed += [line.strip() for line in tool.run(*args).splitlines() if line.strip()]
    return changed


def terraform_docs(
    *, which: Finder = shutil.which, runner: Runner = subprocess.run
) -> CommandRunner:
    """terraform-docs, as found on PATH: a CommandError saying how to install it when not."""
    found = which("terraform-docs")
    if found is None:
        raise CommandError("terraform-docs is not on PATH", hint=TERRAFORM_DOCS_HINT)
    return CommandRunner("terraform-docs", found, runner=runner)
