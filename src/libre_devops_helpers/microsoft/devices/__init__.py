"""Devices across Entra, Defender and Intune: fast checks, watches and a combined view.

The one composite module: it depends on ``core`` and on the ``entra``, ``xdr`` and
``intune`` feature modules, and nothing else. Public API::

    from libre_devops_helpers.core import PollLimits
    from libre_devops_helpers.microsoft.devices import DeviceChecker, Expectations, watch

    checker = DeviceChecker(entra=entra, xdr=xdr)
    run = checker.check(["web01", "web02"], Expectations(tags=("linux-servers",)))
    outcome = watch(checker, names, Expectations(), PollLimits(interval=300, timeout=7200))
"""

from libre_devops_helpers.microsoft.devices.check import DeviceChecker, watch
from libre_devops_helpers.microsoft.devices.inspect import inspect_device
from libre_devops_helpers.microsoft.devices.models import (
    CheckRun,
    DeviceReport,
    DeviceView,
    Expectations,
    Finding,
    Outcome,
)

__all__ = [
    "CheckRun",
    "DeviceChecker",
    "DeviceReport",
    "DeviceView",
    "Expectations",
    "Finding",
    "Outcome",
    "inspect_device",
    "watch",
]
