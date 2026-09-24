"""Why a sign-in lapsed: the Entra ID errors that only a fresh sign-in can clear.

An access token lasts about an hour, and a refresh token renews it without asking
anyone. These errors mean the refresh token itself can no longer be used, so retrying
cannot help: someone has to sign in again. Naming the cause says whether that will keep
happening (a sign-in frequency policy) or was a one-off (a password change).
"""

from __future__ import annotations

import re

# AADSTS code -> the cause, in plain words.
REASONS = {
    "AADSTS700082": "the session went unused for too long, so its refresh token expired",
    "AADSTS70043": "a Conditional Access sign-in frequency policy wants a fresh sign-in",
    "AADSTS70044": "a Conditional Access sign-in frequency policy wants a fresh sign-in",
    "AADSTS50173": "the session was revoked (by an administrator, or by signing out everywhere)",
    "AADSTS50132": "a password change or expiry ended the session",
    "AADSTS50133": "a password change or expiry ended the session",
    "AADSTS50055": "the password has expired",
    "AADSTS50076": "multi-factor authentication is now required",
    "AADSTS50078": "the multi-factor authentication on the session has expired",
    "AADSTS50079": "multi-factor authentication must be set up for this account",
    "AADSTS50158": "an external security challenge was not satisfied",
}
_CODE = re.compile(r"AADSTS\d+")
_SIGNED_OUT = "az login"


def lapse_reason(message: str) -> str | None:
    """The cause when ``message`` says a sign-in lapsed, else None.

    Knows the Entra ID codes above, and the Azure CLI's own ways of saying it has no
    usable session (its messages all tell you to run ``az login``).
    """
    for code in _CODE.findall(message):
        if code in REASONS:
            return REASONS[code]
    if _SIGNED_OUT in message:
        return "the Azure CLI has no usable sign-in for this tenant"
    return None
