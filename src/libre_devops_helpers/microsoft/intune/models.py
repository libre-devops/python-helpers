"""Intune managed devices as returned by Microsoft Graph, trimmed to the fields used here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from libre_devops_helpers.core import fields


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
        """Whether Intune rates the device compliant."""
        return self.compliance_state.casefold() == "compliant"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ManagedDevice:
        """A managed device as Graph returns it."""
        linked = fields.text(data, "azureADDeviceId")
        return cls(
            id=fields.text(data, "id"),
            device_name=fields.text(data, "deviceName"),
            operating_system=fields.text(data, "operatingSystem"),
            os_version=fields.text(data, "osVersion"),
            compliance_state=fields.text(data, "complianceState"),
            management_agent=fields.text(data, "managementAgent"),
            last_sync=fields.when(data, "lastSyncDateTime"),
            enrolled=fields.when(data, "enrolledDateTime"),
            # Intune reports an unlinked device with the all-zero GUID.
            azure_ad_device_id="" if linked == "00000000-0000-0000-0000-000000000000" else linked,
            user_principal_name=fields.text(data, "userPrincipalName"),
            serial_number=fields.text(data, "serialNumber"),
            owner_type=fields.text(data, "managedDeviceOwnerType"),
            raw=dict(data),
        )
