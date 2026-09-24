"""Intune managed devices as returned by Microsoft Graph, trimmed to the fields used here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from libre_devops_helpers.core.util import parse_datetime


@dataclass(frozen=True)
class ManagedDevice:
    """An Intune managed device. ``azure_ad_device_id`` links it to the Entra device."""

    SELECT: ClassVar[str] = (
        "id,deviceName,operatingSystem,osVersion,complianceState,managementAgent,"
        "lastSyncDateTime,enrolledDateTime,azureADDeviceId,userPrincipalName,"
        "serialNumber,managedDeviceOwnerType"
    )

    id: str
    device_name: str
    operating_system: str
    os_version: str
    compliance_state: str
    management_agent: str
    last_sync: datetime | None
    enrolled: datetime | None
    azure_ad_device_id: str
    user_principal_name: str
    serial_number: str
    owner_type: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def compliant(self) -> bool:
        return self.compliance_state.casefold() == "compliant"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ManagedDevice:
        def text(key: str) -> str:
            return str(data.get(key) or "")

        return cls(
            id=text("id"),
            device_name=text("deviceName"),
            operating_system=text("operatingSystem"),
            os_version=text("osVersion"),
            compliance_state=text("complianceState"),
            management_agent=text("managementAgent"),
            last_sync=parse_datetime(data.get("lastSyncDateTime")),
            enrolled=parse_datetime(data.get("enrolledDateTime")),
            # Intune reports an unlinked device with the all-zero GUID.
            azure_ad_device_id=""
            if text("azureADDeviceId") == "00000000-0000-0000-0000-000000000000"
            else text("azureADDeviceId"),
            user_principal_name=text("userPrincipalName"),
            serial_number=text("serialNumber"),
            owner_type=text("managedDeviceOwnerType"),
            raw=dict(data),
        )
