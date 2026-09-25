"""Entra objects as Graph returns them, for the entra command tests."""

GROUP_ID = "55555555-5555-5555-5555-555555555555"
USER_ID = "88888888-8888-8888-8888-888888888888"
DEVICE_ID = "66666666-6666-6666-6666-666666666666"
# A second registration with the same name, as a stale one leaves behind.
STALE_ID = "67676767-6767-6767-6767-676767676767"
GROUPS = "/v1.0/groups"
# Graph's reply for the user ana@example.com.
ANA = (200, {"id": USER_ID, "displayName": "Ana", "userPrincipalName": "ana@example.com"})


def device(object_id: str = DEVICE_ID) -> dict:
    return {
        "id": object_id,
        "displayName": "web01",
        "operatingSystem": "Linux",
        "operatingSystemVersion": "9.4",
        "accountEnabled": True,
        "trustType": "ServerAd",
    }


def group(name: str = "Ring 1", *, dynamic: bool = False) -> dict:
    return {
        "id": GROUP_ID,
        "displayName": name,
        "groupTypes": ["DynamicMembership"] if dynamic else [],
        "securityEnabled": True,
    }
