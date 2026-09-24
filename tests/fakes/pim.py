"""PIM replies shared by the Azure resource, Entra role and group tests."""

from urllib.parse import parse_qs, urlsplit

ME = "88888888-8888-8888-8888-888888888888"

RULES = [
    {
        "id": "Expiration_EndUser_Assignment",
        "isExpirationRequired": True,
        "maximumDuration": "PT8H",
    },
    {
        "id": "Enablement_EndUser_Assignment",
        "enabledRules": ["MultiFactorAuthentication", "Justification"],
    },
    {
        "id": "Approval_EndUser_Assignment",
        "setting": {
            "isApprovalRequired": True,
            "approvalStages": [{"primaryApprovers": [{"description": "Security Leads"}]}],
        },
    },
    {"id": "AuthenticationContext_EndUser_Assignment", "isEnabled": True, "claimValue": "c1"},
    {
        "id": "Expiration_Admin_Eligibility",
        "isExpirationRequired": False,
        "maximumDuration": "P365D",
    },
    {"id": "Expiration_Admin_Assignment", "isExpirationRequired": True, "maximumDuration": "P180D"},
]


def query(request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(request.url).query).items()}
