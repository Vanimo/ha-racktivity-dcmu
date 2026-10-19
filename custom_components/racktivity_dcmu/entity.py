"""Base entities for the Racktivity DCMU integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DcmuCoordinator, DcmuHttpCoordinator
from .pdu import Outlet


def pdu_device_info(coordinator: DcmuCoordinator) -> DeviceInfo:
    """Device info of the PDU itself."""
    entry = coordinator.config_entry
    state = coordinator.data
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=state.model or "DCMU",
        name=state.name or "Racktivity PDU",
        configuration_url=f"http://{entry.data[CONF_HOST]}/",
    )


def outlet_device_info(coordinator: DcmuCoordinator, index: int) -> DeviceInfo:
    """Device info of one outlet, linked to the PDU device."""
    entry = coordinator.config_entry
    outlet = coordinator.data.outlets[index]
    pdu_name = coordinator.data.name or "Racktivity PDU"
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_outlet{outlet.number}")},
        manufacturer=MANUFACTURER,
        model="Outlet",
        name=f"{pdu_name} {outlet.name or f'Outlet {outlet.number}'}",
        **_via_pdu(coordinator.hass, entry.entry_id),
    )


def _via_pdu(hass: HomeAssistant, entry_id: str) -> dict:
    """Link an outlet device to the PDU device (via_device_id on HA >= 2026.x)."""
    lookup = getattr(dr, "async_get_device_id_by_identifier", None)
    if lookup is None:
        return {"via_device": (DOMAIN, entry_id)}
    return {"via_device_id": lookup(hass, (DOMAIN, entry_id), config_entry_id=entry_id)}


class DcmuEntity(CoordinatorEntity[DcmuCoordinator]):
    """SNMP entity on the PDU device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DcmuCoordinator, description: EntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = pdu_device_info(coordinator)


class DcmuOutletEntity(CoordinatorEntity[DcmuCoordinator]):
    """SNMP entity on one outlet's device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DcmuCoordinator, description: EntityDescription, index: int
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self.index = index
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_outlet{index + 1}_{description.key}"
        self._attr_device_info = outlet_device_info(coordinator, index)

    @property
    def outlet(self) -> Outlet:
        """Current data for this outlet."""
        return self.coordinator.data.outlets[self.index]


class DcmuHttpEntity(CoordinatorEntity[DcmuHttpCoordinator]):
    """Web API entity, on the PDU device or (with index) an outlet device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DcmuHttpCoordinator,
        description: EntityDescription,
        index: int | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self.index = index
        entry_id = coordinator.config_entry.entry_id
        if index is None:
            self._attr_unique_id = f"{entry_id}_{description.key}"
            self._attr_device_info = pdu_device_info(coordinator.snmp)
        else:
            self._attr_unique_id = f"{entry_id}_outlet{index + 1}_{description.key}"
            self._attr_device_info = outlet_device_info(coordinator.snmp, index)
