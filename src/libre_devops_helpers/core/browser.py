"""Whether a browser can be opened here, decided as the Azure CLI decides it."""

from __future__ import annotations

import sys
import webbrowser


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
