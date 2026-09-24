"""Intune through Microsoft Graph: managed devices and their compliance.

Depends only on ``core`` and the shared Microsoft layer. The Azure CLI's Graph token
cannot read Intune, so this needs a profile whose credential has
``DeviceManagementManagedDevices.Read.All``. Public API::

    from libre_devops_helpers.microsoft.intune import IntuneClient

    with IntuneClient.for_profile(profile, tokens) as intune:
        for device in intune.find_devices("laptop-042"):
            print(device.device_name, device.compliance_state)
"""

from libre_devops_helpers.microsoft.intune.client import IntuneClient
from libre_devops_helpers.microsoft.intune.models import ManagedDevice
from libre_devops_helpers.microsoft.intune.permissions import REQUIREMENTS

__all__ = ["REQUIREMENTS", "IntuneClient", "ManagedDevice"]
