"""What each Defender for Endpoint feature needs from a token.

These are the application permissions and granular delegated scopes. The Azure CLI's
Defender token carries only ``user_impersonation``, in which case the token checks say
access rests on the user's Defender role instead of listing these.
"""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "xdr machines",
        "mde",
        (("Machine.Read.All", "Machine.ReadWrite.All", "Machine.Read", "Machine.ReadWrite"),),
    ),
    Requirement(
        "xdr alerts",
        "mde",
        (("Alert.Read.All", "Alert.ReadWrite.All", "Alert.Read", "Alert.ReadWrite"),),
    ),
    Requirement("xdr vulnerabilities", "mde", (("Vulnerability.Read.All", "Vulnerability.Read"),)),
    Requirement("xdr indicators", "mde", (("Ti.Read.All", "Ti.ReadWrite", "Ti.ReadWrite.All"),)),
    Requirement("xdr hunting", "mde", (("AdvancedQuery.Read.All", "AdvancedQuery.Read"),)),
)
