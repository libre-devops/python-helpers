"""Writing a module's README from its HEADER.md and terraform-docs, or checking it is."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from libre_devops_helpers.core.errors import CommandError, InputError
from libre_devops_helpers.core.process import CommandRunner
from libre_devops_helpers.core.text_files import TextFile, read_text, write_text

BEGIN = "<!-- BEGIN_TF_DOCS -->"
END = "<!-- END_TF_DOCS -->"
HEADER = "HEADER.md"
README = "README.md"
CONFIG = ".terraform-docs.yml"


@dataclass(frozen=True)
class Readme:
    """What became of one module's README: ``updated``, ``up to date`` or, when only
    checked, ``out of date``; and the header file its top came from, if any."""

    folder: Path
    path: Path
    header: Path | None
    state: str


def with_header(readme: str, header: str | None, newline: str = "\n") -> str:
    """``readme`` with ``header`` above its terraform-docs section, keeping the section and
    whatever follows it, and ending in a line break. Without a header its own top is kept;
    either way the section's markers are added when it has none, for terraform-docs to
    write between."""
    start = readme.find(BEGIN)
    if start >= 0 and readme.find(END, start) < 0:
        raise InputError(f"it has {BEGIN} but no {END} after it")
    if start >= 0:
        top, section = readme[:start], readme[start:]
    else:
        top, section = readme, f"{BEGIN}{newline}{END}{newline}"
    if header is not None:
        top = header
    if not section.endswith("\n"):
        section += newline
    return top.rstrip() + newline * 2 + section if top.strip() else section


def document(
    folder: Path,
    *,
    tool: CommandRunner,
    check: bool,
    header_name: str = HEADER,
    readme_name: str = README,
) -> Readme:
    """Put the folder's header file (when it has one) at the top of its README and run
    terraform-docs to write the rest; or, with ``check``, change nothing and say whether
    doing so would change the README."""
    header_path = folder / header_name
    header = read_text(header_path).text if header_path.is_file() else None
    readme_path = folder / readme_name
    before = read_text(readme_path) if readme_path.is_file() else TextFile(readme_path, "")
    try:
        wanted = with_header(before.text, header, before.newline)
    except InputError as exc:
        raise InputError(f"{readme_path}: {exc}", hint=exc.hint) from None
    used = header_path if header is not None else None
    if check:
        fresh = wanted == before.text and _generated(tool, folder, readme_name)
        return Readme(folder, readme_path, used, "up to date" if fresh else "out of date")
    if wanted != before.text:
        write_text(before, wanted)
    tool.run(*_arguments(folder, readme_name, check=False))
    after = read_text(readme_path).text
    return Readme(folder, readme_path, used, "up to date" if after == before.text else "updated")


def folders(paths: Sequence[Path], *, recursive: bool, header_name: str = HEADER) -> list[Path]:
    """The module folders to document: each of ``paths``, and with ``recursive`` every
    folder beneath one that has a header file of its own (an example, a submodule)."""
    found: list[Path] = []
    for path in paths:
        if not path.is_dir():
            raise InputError(f"{path} is not a folder", hint="give the module's folder")
        found.append(path)
        if recursive:
            found += _beneath(path, header_name)
    return found


def _beneath(root: Path, header_name: str) -> list[Path]:
    found: list[Path] = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = sorted(name for name in subfolders if not name.startswith("."))
        if Path(folder) != root and header_name in files:
            found.append(Path(folder))
    return found


def _generated(tool: CommandRunner, folder: Path, readme_name: str) -> bool:
    """Whether terraform-docs would leave the README's section as it is."""
    try:
        tool.run(*_arguments(folder, readme_name, check=True))
    except CommandError as exc:
        if "out of date" in str(exc):
            return False
        raise
    return True


def _arguments(folder: Path, readme_name: str, *, check: bool) -> list[str]:
    """terraform-docs' arguments: the module's own .terraform-docs.yml, which terraform-docs
    reads from the module's folder, else a Markdown table injected into the README."""
    checking = ["--output-check"] if check else []
    if (folder / CONFIG).is_file():
        return [*checking, str(folder)]
    inject = ["--output-file", readme_name, "--output-mode", "inject"]
    return ["markdown", "table", *inject, *checking, str(folder)]
