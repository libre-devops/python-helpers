"""Whether a browser can be opened here, decided as the Azure CLI decides it, and
opening one without letting a failure stop a sign-in."""

from __future__ import annotations

import logging
import sys
import webbrowser
from collections.abc import Callable

log = logging.getLogger(__name__)


def can_launch_browser() -> bool:
    """False on a Linux machine with no browser to open (a headless server, say).

    Windows and macOS always have one. On Linux, a browser registered with Python's
    webbrowser module (a desktop session, or BROWSER set) counts.
    """
    if not sys.platform.startswith("linux"):
        return True
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def open_quietly(open_browser: Callable[[str], object], url: str) -> None:
    """Open ``url`` with ``open_browser``, if it can. The link has been shown already, so
    a browser that will not start only costs the person a click, and is only logged."""
    try:
        open_browser(url)
    except Exception:  # any browser launcher's failure, from any platform
        log.debug("could not open a browser", exc_info=True)
