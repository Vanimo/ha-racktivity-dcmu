"""Read-only outlet relay state, used while control is disabled."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import control_enabled
from .coordinator import DcmuConfigEntry
from .entity import DcmuHttpEntity, DcmuOutletEntity
from .pdu import NUM_OUTLETS

PARALLEL_UPDATES = 0

RELAY = BinarySensorEntityDescription(
    key="relay",
    name=None,
    device_class=BinarySensorDeviceClass.POWER,
)

INTRUSION = tuple(
    BinarySensorEntityDescription(
        key=f"intrusion_{n}",
        translation_key="intrusion",
        translation_placeholders={"input": str(n)},
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_registry_enabled_default=False,
    )
    for n in (1, 2)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DcmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up outlet relay state sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    if not control_enabled(entry):
        entities += [OutletRelaySensor(coordinator, RELAY, i) for i in range(NUM_OUTLETS)]
    if coordinator.http is not None:
        entities += [IntrusionSensor(coordinator.http, d) for d in INTRUSION]
    async_add_entities(entities)


class OutletRelaySensor(DcmuOutletEntity, BinarySensorEntity):
    """Relay state of one outlet."""

    @property
    def is_on(self) -> bool | None:
        return self.outlet.is_on


class IntrusionSensor(DcmuHttpEntity, BinarySensorEntity):
    """Intrusion input 1 or 2 (web API)."""

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.intrusion is None:
            return None
        return data.intrusion[0 if self.entity_description.key.endswith("1") else 1]
