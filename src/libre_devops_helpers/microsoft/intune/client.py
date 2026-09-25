"""Read-only Intune managed device queries through Microsoft Graph v1.0."""

from __future__ import annotations

from datetime import UTC, datetime

from libre_devops_helpers.core.util import candidate_names, odata_string, require_guid
from libre_devops_helpers.microsoft.api_clients import GraphServiceClient
from libre_devops_helpers.microsoft.intune.models import ManagedDevice

_PATH = "/v1.0/deviceManagement/managedDevices"
_NEVER = datetime.min.replace(tzinfo=UTC)


class IntuneClient(GraphServiceClient):
    """Intune managed device lookups. Close it (or use ``with``) when done."""

    API_NAME = "Intune (Microsoft Graph)"

    def find_devices(self, name: str) -> list[ManagedDevice]:
        """Managed devices named ``name``, else its short hostname, newest sync first."""
        for candidate in candidate_names(name):
            found = self._query(f"deviceName eq {odata_string(candidate)}")
            if found:
                return found
        return []

    def for_entra_device(self, device_id: str) -> list[ManagedDevice]:
        """Managed devices linked to an Entra ``deviceId`` (not its object id)."""
        device_id = require_guid(device_id, "an Entra device id")
        return self._query(f"azureADDeviceId eq {odata_string(device_id)}")

    def _query(self, expression: str) -> list[ManagedDevice]:
        items = self.api.get_all(
            _PATH, params={"$filter": expression, "$select": ManagedDevice.SELECT}
        )
        devices = [ManagedDevice.from_json(item) for item in items]
        return sorted(devices, key=lambda device: device.last_sync or _NEVER, reverse=True)
