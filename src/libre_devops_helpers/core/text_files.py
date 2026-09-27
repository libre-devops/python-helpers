"""Text files changed in place as they were written: UTF-8 with or without a byte order
mark, either line ending, and a whole new file renamed into place so nothing ever reads half
of one."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from libre_devops_helpers.core.errors import InputError

_BOM = "﻿"


@dataclass(frozen=True)
class TextFile:
    """A file's text (without a byte order mark), and how it was written."""

    path: Path
    text: str
    bom: bool = False
    newline: str = "\n"


def read_text(path: Path) -> TextFile:
    """The file at ``path``: an InputError when it cannot be read, or is not UTF-8."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(f"{path} is not UTF-8 text") from None
    bom = text.startswith(_BOM)
    text = text.removeprefix(_BOM)
    return TextFile(path, text, bom, "\r\n" if "\r\n" in text else "\n")


def write_text(file: TextFile, text: str) -> None:
    """Replace ``file`` with ``text``, keeping its byte order mark and its permissions.

    The text goes to a temporary file beside it first, renamed over it once complete.
    """
    folder = file.path.parent
    try:
        handle, name = tempfile.mkstemp(dir=folder, prefix=f".{file.path.name}.", suffix=".tmp")
    except OSError as exc:
        raise InputError(f"cannot write in {folder}: {exc.strerror or exc}") from None
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write((_BOM if file.bom else "") + text)
        with contextlib.suppress(OSError):  # a file system without modes keeps its own
            shutil.copymode(file.path, temporary)
        os.replace(temporary, file.path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise InputError(f"cannot write {file.path}: {exc.strerror or exc}") from None
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
