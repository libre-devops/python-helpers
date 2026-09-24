"""What the Intune feature needs from a Graph token. The Azure CLI's token has neither."""

from libre_devops_helpers.microsoft.resources import Requirement

REQUIREMENTS = (
    Requirement(
        "intune devices",
        "graph",
        (
            (
                "DeviceManagementManagedDevices.Read.All",
                "DeviceManagementManagedDevices.ReadWrite.All",
            ),
        ),
    ),
)
