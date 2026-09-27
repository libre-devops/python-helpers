import pytest

from libre_devops_helpers.microsoft.analyzer.catalogue import CHECKS, describe


@pytest.mark.parametrize(
    ("finding_id", "expected"),
    [
        ("330002", ("linux", "informational", "Connectivity", "EDR cloud (command and control)")),
        ("231004", ("macos", "warning", "Connectivity", "EDR cloud (cyber data)")),
        ("312002", ("linux", "error", "Processes", "Defender processes")),
        ("399999", ("linux", "informational", "Other", "check 399999")),
    ],
    ids=["linux-good", "macos-warning", "linux-error", "unknown"],
)
def test_an_id_says_its_platform_severity_and_check(finding_id, expected):
    assert describe(finding_id)[:4] == expected


def test_every_known_check_has_the_severity_its_code_says():
    # The second digit of the code is the severity: 0 good, 1 warning, 2 error.
    for code in CHECKS:
        assert code[1] in "012", code
