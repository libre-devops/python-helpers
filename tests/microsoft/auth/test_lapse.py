import pytest

from libre_devops_helpers.microsoft.auth import lapse_reason


@pytest.mark.parametrize(
    ("message", "cause"),
    [
        ("AADSTS700082: The refresh token has expired due to inactivity.", "went unused"),
        ("AADSTS70043: The refresh token has expired ... sign-in frequency", "sign-in frequency"),
        ("AADSTS50173: The provided grant has expired due to it being revoked", "revoked"),
        ("AADSTS50133: Session is invalid due to expiration or recent password change", "password"),
        ("AADSTS50076: you must use multi-factor authentication", "multi-factor"),
        ("Please run 'az login' to setup account.", "no usable sign-in"),
        ("Interactive authentication is needed. Please run: az login --scope x", "no usable"),
    ],
)
def test_lapsed_sign_ins_are_named(message, cause):
    assert cause in (lapse_reason(message) or "")


def test_a_known_code_wins_over_the_generic_az_login_advice():
    message = "AADSTS70043: sign-in frequency. To re-authenticate, please run: az login"
    assert "sign-in frequency" in (lapse_reason(message) or "")


@pytest.mark.parametrize(
    "message",
    [
        "AADSTS65001: The user or administrator has not consented",
        "Unable to get authority configuration for https://login.microsoftonline.com/x",
        "HTTPSConnectionPool(host='login.microsoftonline.com'): Max retries exceeded",
    ],
)
def test_other_failures_are_not_a_lapse(message):
    assert lapse_reason(message) is None
