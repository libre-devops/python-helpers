"""Encrypt bytes for the signed-in Windows account with DPAPI, through ctypes.

``CryptProtectData`` ties the result to the Windows account (and this machine), so only
that account can decrypt it; the brand name is mixed in as extra entropy, so another
program running as the same account cannot decrypt it by asking DPAPI alone. Windows
only: the Windows CI job tests it.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from typing import Any

from libre_devops_helpers.core import brand

_ENTROPY = f"{brand.COMMAND} refresh tokens".encode()
_UI_FORBIDDEN = 0x01  # never show a prompt


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_char))]


def protect(data: bytes) -> bytes:  # pragma: no cover - Windows only
    """``data`` encrypted for the current Windows account."""
    return _crypt(_library("crypt32").CryptProtectData, data)


def unprotect(data: bytes) -> bytes:  # pragma: no cover - Windows only
    """``data`` decrypted; OSError when it was encrypted for another account."""
    return _crypt(_library("crypt32").CryptUnprotectData, data)


def _library(name: str) -> Any:  # pragma: no cover - Windows only
    # use_last_error keeps the call's error code, which a later call could overwrite.
    return ctypes.WinDLL(name, use_last_error=True)  # type: ignore[attr-defined]


def _crypt(function: Callable[..., Any], data: bytes) -> bytes:  # pragma: no cover - Windows
    source = ctypes.create_string_buffer(data, len(data))
    entropy = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    blob_in = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    blob_entropy = _Blob(len(_ENTROPY), ctypes.cast(entropy, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    # Both functions take (in, description, entropy, reserved, prompt, flags, out).
    if not function(
        ctypes.byref(blob_in),
        None,
        ctypes.byref(blob_entropy),
        None,
        None,
        _UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    try:
        return ctypes.string_at(blob_out.data, blob_out.size)
    finally:
        _library("kernel32").LocalFree(blob_out.data)
