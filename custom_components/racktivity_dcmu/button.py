"""Power-cycle button per outlet (only with control enabled)."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import CycleInProgress, DcmuConfigEntry
from .entity import DcmuOutletEntity
from .pdu import NUM_OUTLETS
from .snmp import SnmpError

PARALLEL_UPDATES = 1

POWER_CYCLE = ButtonEntityDescription(
    key="power_cycle",
    translation_key="power_cycle",
    device_class=ButtonDeviceClass.RESTART,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DcmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one power-cycle button per outlet."""
    coordinator = entry.runtime_data
    async_add_entities(PowerCycleButton(coordinator, POWER_CYCLE, i) for i in range(NUM_OUTLETS))


class PowerCycleButton(DcmuOutletEntity, ButtonEntity):
    """Switch the outlet off and back on after the configured delay."""

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_power_cycle(self.index)
        except CycleInProgress as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cycle_in_progress",
                translation_placeholders={"outlet": str(self.outlet.number)},
            ) from err
        except SnmpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="relay_failed",
                translation_placeholders={"outlet": str(self.outlet.number), "error": str(err)},
            ) from err
