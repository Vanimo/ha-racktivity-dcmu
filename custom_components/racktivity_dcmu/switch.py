"""Outlet relay switches (only set up when control is enabled)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import DcmuConfigEntry
from .entity import DcmuOutletEntity
from .pdu import NUM_OUTLETS
from .snmp import SnmpError

# Relay writes go to a small embedded agent; one at a time.
PARALLEL_UPDATES = 1

RELAY = SwitchEntityDescription(
    key="relay",
    name=None,
    device_class=SwitchDeviceClass.OUTLET,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DcmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up outlet switches."""
    coordinator = entry.runtime_data
    async_add_entities(OutletSwitch(coordinator, RELAY, i) for i in range(NUM_OUTLETS))


class OutletSwitch(DcmuOutletEntity, SwitchEntity):
    """Relay of one outlet."""

    @property
    def is_on(self) -> bool | None:
        return self.outlet.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        try:
            await self.coordinator.pdu.set_relay(self.index, on)
        except SnmpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="relay_failed",
                translation_placeholders={"outlet": str(self.outlet.number), "error": str(err)},
            ) from err
        # Read back right away (not debounced): the user is waiting on it.
        self.coordinator.request_config_refresh()
        await self.coordinator.async_refresh()
