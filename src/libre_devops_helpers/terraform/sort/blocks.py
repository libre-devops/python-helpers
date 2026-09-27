"""Sorting a file's variable and output blocks by name, and finding the files to sort."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from libre_devops_helpers.core.errors import InputError
from libre_devops_helpers.core.text_files import read_text, write_text
from libre_devops_helpers.terraform.hcl import Piece, split

# The kinds of block sorted: a module's inputs and its outputs.
KINDS = ("variable", "output")
# Where a module keeps each, by convention.
FILES = {"variable": "variables.tf", "output": "outputs.tf"}


@dataclass(frozen=True)
class Sorting:
    """What sorting one kind of block in one file found: how many, whether they were in
    order already, and whether the file was written to put them in order."""

    path: Path
    kind: str
    count: int
    in_order: bool
    written: bool = False


def order_key(name: str) -> tuple[str, str]:
    """How names sort: ignoring case, then as written, a character at a time, as
    terraform-docs orders a README's inputs and outputs, so a file and its README agree."""
    return (name.casefold(), name)


def sort_text(text: str, kind: str) -> tuple[str, int, bool]:
    """``text`` with its ``kind`` blocks in name order, each where one of them stood; how
    many there are; and whether they were in order already (``text`` itself, then)."""
    pieces = split(text)
    slots = [at for at, piece in enumerate(pieces) if piece.kind == kind]
    blocks = [pieces[at] for at in slots]
    ordered = sorted(blocks, key=lambda piece: order_key(piece.name or ""))
    if [piece.name for piece in ordered] == [piece.name for piece in blocks]:
        return text, len(blocks), True
    for at, piece in zip(slots, ordered, strict=True):
        pieces[at] = piece
    newline = "\r\n" if "\r\n" in text else "\n"
    return "".join(_ended(piece, newline) for piece in pieces), len(blocks), False


def sort_file(path: Path, kinds: Sequence[str], *, write: bool) -> list[Sorting]:
    """Sort each of ``kinds`` of block in the file at ``path``, writing it only when
    ``write`` and something moved: what each found."""
    file = read_text(path)
    text = file.text
    found: list[Sorting] = []
    for kind in kinds:
        try:
            text, count, in_order = sort_text(text, kind)
        except InputError as exc:
            raise InputError(f"{path}: {exc}", hint=exc.hint) from None
        found.append(Sorting(path, kind, count, in_order, written=write and not in_order))
    if write and text != file.text:
        write_text(file, text)
    return found


def targets(
    paths: Sequence[Path], kinds: Sequence[str], *, recursive: bool
) -> list[tuple[Path, tuple[str, ...]]]:
    """The files to sort, and the kinds of block to sort in each: a file named, for all of
    ``kinds``; a folder's variables.tf for its variables and outputs.tf for its outputs,
    and with ``recursive`` those of every folder beneath it (examples/, modules/)."""
    found: list[tuple[Path, tuple[str, ...]]] = []
    for path in paths:
        if path.is_file():
            found.append((path, tuple(kinds)))
            continue
        if not path.is_dir():
            raise InputError(f"{path} is not a file or a folder")
        for folder in _folders(path, recursive=recursive):
            found += [(folder / FILES[kind], (kind,)) for kind in kinds if _has(folder, kind)]
    if not found:
        names = " or ".join(FILES[kind] for kind in kinds)
        raise InputError(f"no {names} to sort there", hint="name the .tf files to sort")
    return found


def _has(folder: Path, kind: str) -> bool:
    return (folder / FILES[kind]).is_file()


def _folders(root: Path, *, recursive: bool) -> list[Path]:
    """``root``, and with ``recursive`` every folder beneath it but hidden ones, such as
    .terraform (downloaded modules, not this one's) and .git."""
    if not recursive:
        return [root]
    found: list[Path] = []
    for folder, subfolders, _ in os.walk(root):
        subfolders[:] = sorted(name for name in subfolders if not name.startswith("."))
        found.append(Path(folder))
    return found


def _ended(piece: Piece, newline: str) -> str:
    """A piece's text ending in a line break, so a block moved up from the end of a file
    that has none still starts the next one on a line of its own."""
    return piece.text if piece.text.endswith("\n") else piece.text + newline
