"""Binary sensors: relay state (read-only mode), over-limit problems, intrusion inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import control_enabled
from .coordinator import DcmuConfigEntry
from .entity import DcmuEntity, DcmuHttpEntity, DcmuOutletEntity
from .pdu import NUM_OUTLETS, Outlet, PduState

PARALLEL_UPDATES = 0

RELAY = BinarySensorEntityDescription(
    key="relay",
    name=None,
    device_class=BinarySensorDeviceClass.POWER,
)


@dataclass(frozen=True, kw_only=True)
class PduProblemDescription(BinarySensorEntityDescription):
    """Problem flag computed from PDU values and the device's own limits."""

    value_fn: Callable[[PduState], bool | None]


@dataclass(frozen=True, kw_only=True)
class OutletProblemDescription(BinarySensorEntityDescription):
    """Problem flag computed from outlet values and the device's own limits."""

    value_fn: Callable[[Outlet], bool | None]


def _at_or_above(value: float | None, limit: float | None) -> bool | None:
    if value is None or limit is None:
        return None
    return value >= limit


def _voltage_out_of_range(s: PduState) -> bool | None:
    if s.voltage is None or s.voltage_min is None or s.voltage_max is None:
        return None
    return not s.voltage_min <= s.voltage <= s.voltage_max


PDU_PROBLEMS: tuple[PduProblemDescription, ...] = (
    PduProblemDescription(
        key="over_total_warning_level",
        translation_key="over_total_warning_level",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: _at_or_above(s.current, s.total_warning_current),
    ),
    PduProblemDescription(
        key="voltage_out_of_range",
        translation_key="voltage_out_of_range",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_voltage_out_of_range,
    ),
)

OUTLET_PROBLEM = OutletProblemDescription(
    key="over_warning_level",
    translation_key="over_warning_level",
    device_class=BinarySensorDeviceClass.PROBLEM,
    value_fn=lambda o: _at_or_above(o.current, o.warning_current),
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
    """Set up relay state (read-only mode), problem and intrusion sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    if not control_enabled(entry):
        entities += [OutletRelaySensor(coordinator, RELAY, i) for i in range(NUM_OUTLETS)]
    entities += [PduProblemSensor(coordinator, d) for d in PDU_PROBLEMS]
    entities += [OutletProblemSensor(coordinator, OUTLET_PROBLEM, i) for i in range(NUM_OUTLETS)]
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


class PduProblemSensor(DcmuEntity, BinarySensorEntity):
    """PDU-level problem flag."""

    entity_description: PduProblemDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)


class OutletProblemSensor(DcmuOutletEntity, BinarySensorEntity):
    """Outlet draws at or above its warning level."""

    entity_description: OutletProblemDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.outlet)
