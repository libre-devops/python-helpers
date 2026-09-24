"""Read-only Intune managed device queries through Microsoft Graph v1.0."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

import requests

from libre_devops_helpers.core.auth import TokenProvider, token_source
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.http import ApiClient
from libre_devops_helpers.core.util import candidate_names, is_guid, odata_string
from libre_devops_helpers.microsoft.clouds import PUBLIC
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.intune.models import ManagedDevice

_PATH = "/v1.0/deviceManagement/managedDevices"
_NEVER = datetime.min.replace(tzinfo=UTC)


class IntuneClient:
    """Intune managed device lookups. Close it (or use ``with``) when done."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api

    @classmethod
    def create(
        cls,
        tokens: TokenProvider,
        tenant_id: str,
        *,
        graph_url: str = PUBLIC.graph_url,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> IntuneClient:
        """A client for ``tenant_id`` that takes its Graph tokens from ``tokens``."""
        api = ApiClient(
            graph_url,
            token_source(tokens, graph_url, tenant_id),
            name="Intune (Microsoft Graph)",
            verify=verify,
            session=session,
        )
        return cls(api)

    @classmethod
    def for_profile(
        cls,
        profile: Profile,
        tokens: TokenProvider,
        *,
        verify: bool | str = True,
        session: requests.Session | None = None,
    ) -> IntuneClient:
        """A client for a configured profile's tenant, in the profile's cloud."""
        return cls.create(
            tokens,
            profile.tenant_id,
            graph_url=profile.cloud.graph_url,
            verify=verify,
            session=session,
        )

    def close(self) -> None:
        self.api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def find_devices(self, name: str) -> list[ManagedDevice]:
        """Managed devices named ``name``, else its short hostname, newest sync first."""
        for candidate in candidate_names(name):
            found = self._query(f"deviceName eq {odata_string(candidate)}")
            if found:
                return found
        return []

    def for_entra_device(self, device_id: str) -> list[ManagedDevice]:
        """Managed devices linked to an Entra ``deviceId`` (not its object id)."""
        if not is_guid(device_id):
            raise LdoError(f"not an Entra device id: {device_id!r}")
        return self._query(f"azureADDeviceId eq {odata_string(device_id.strip())}")

    def _query(self, expression: str) -> list[ManagedDevice]:
        items = self.api.get_all(
            _PATH, params={"$filter": expression, "$select": ManagedDevice.SELECT}
        )
        devices = [ManagedDevice.from_json(item) for item in items]
        return sorted(devices, key=lambda device: device.last_sync or _NEVER, reverse=True)
