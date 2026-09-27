"""What each Linux and macOS analyzer finding means.

The Linux and macOS analyzer records a finding as an id alone: its platform (3 Linux,
2 macOS), then five digits, the second of which is the severity (0 good, 1 warning,
2 error). Its catalogue of what each means ships beside the tool, not in its results, so
the checks it has are described here, and one this does not know is still shown, by id.
"""

from __future__ import annotations

PLATFORMS = {"1": "windows", "2": "macos", "3": "linux"}
_SEVERITY_DIGITS = {"0": "informational", "1": "warning", "2": "error"}

_EDR_CNC = "EDR cloud (command and control)"
_EDR_CYBER = "EDR cloud (cyber data)"
_AV_CLOUD = "Antivirus cloud"
_ALL_PASSED = "every test connection succeeded"
_SOME_FAILED = "some test connections failed"
_ALL_FAILED = "the test connections failed"

# By the five digits after the platform: (category, check, result).
CHECKS: dict[str, tuple[str, str, str]] = {
    "30002": ("Connectivity", _EDR_CNC, _ALL_PASSED),
    "31001": ("Connectivity", _EDR_CNC, _SOME_FAILED),
    "32003": ("Connectivity", _EDR_CNC, _ALL_FAILED),
    "30005": ("Connectivity", _EDR_CYBER, _ALL_PASSED),
    "31004": ("Connectivity", _EDR_CYBER, _SOME_FAILED),
    "32006": ("Connectivity", _EDR_CYBER, _ALL_FAILED),
    "30008": ("Connectivity", _AV_CLOUD, _ALL_PASSED),
    "31007": ("Connectivity", _AV_CLOUD, _SOME_FAILED),
    "32009": ("Connectivity", _AV_CLOUD, _ALL_FAILED),
    "12001": ("Environment", "Operating system", "not supported"),
    "10038": ("Environment", "Operating system", "supported in preview"),
    "10002": ("Processes", "Defender processes", "running"),
    "12002": ("Processes", "Defender processes", "not running"),
    "11010": ("Environment", "Conflicting binaries", "other software with audit rules found"),
    "21035": ("Anti-spoofing", "Anti-spoofing", "ready, not yet stable"),
    "21036": ("Anti-spoofing", "Anti-spoofing", "unstable"),
    "20037": ("Anti-spoofing", "Anti-spoofing", "stable"),
}

# What to read when a category's check is not good, by platform.
GUIDANCE: dict[tuple[str, str], str] = {
    ("linux", "Connectivity"): (
        "Allow the Defender for Endpoint addresses through the proxy and firewall: "
        "https://learn.microsoft.com/defender-endpoint/linux-support-connectivity"
    ),
    ("linux", "Environment"): (
        "Check the system requirements: "
        "https://learn.microsoft.com/defender-endpoint/microsoft-defender-endpoint-linux"
    ),
}


def describe(finding_id: str) -> tuple[str, str, str, str, str]:
    """(platform, severity, category, check, result) for a Linux or macOS finding id; one
    this does not know keeps its id as its check."""
    platform = PLATFORMS.get(finding_id[:1], "")
    code = finding_id[1:]
    severity = _SEVERITY_DIGITS.get(code[1:2], "informational")
    category, check, result = CHECKS.get(code, ("Other", f"check {finding_id}", ""))
    return platform, severity, category, check, result
