"""Sensors for the Racktivity DCMU."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DcmuConfigEntry
from .entity import DcmuEntity, DcmuHttpEntity, DcmuOutletEntity
from .http_api import HttpState
from .pdu import NUM_OUTLETS, Outlet, PduState

type StateValue = float | int | datetime | None

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PduSensorDescription(SensorEntityDescription):
    """Sensor on the PDU device."""

    value_fn: Callable[[PduState], StateValue]


@dataclass(frozen=True, kw_only=True)
class OutletSensorDescription(SensorEntityDescription):
    """Sensor on an outlet device."""

    value_fn: Callable[[Outlet], StateValue]


_CURRENT: dict[str, Any] = {
    "device_class": SensorDeviceClass.CURRENT,
    "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
    "suggested_display_precision": 3,
}
_LIMIT: dict[str, Any] = {
    **_CURRENT,
    "suggested_display_precision": 1,
    "entity_category": EntityCategory.DIAGNOSTIC,
    "entity_registry_enabled_default": False,
}
_ENERGY: dict[str, Any] = {
    "device_class": SensorDeviceClass.ENERGY,
    "state_class": SensorStateClass.TOTAL_INCREASING,
    "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    "suggested_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "suggested_display_precision": 3,
}
_PEAK_TIME: dict[str, Any] = {
    "device_class": SensorDeviceClass.TIMESTAMP,
    "entity_category": EntityCategory.DIAGNOSTIC,
    "entity_registry_enabled_default": False,
}

PDU_SENSORS: tuple[PduSensorDescription, ...] = (
    PduSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        value_fn=lambda s: s.voltage,
    ),
    PduSensorDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        suggested_display_precision=2,
        value_fn=lambda s: s.frequency,
    ),
    PduSensorDescription(
        key="current",
        translation_key="total_current",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.current,
        **_CURRENT,
    ),
    PduSensorDescription(
        key="power",
        translation_key="total_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda s: s.power,
    ),
    PduSensorDescription(
        key="energy",
        translation_key="total_energy",
        value_fn=lambda s: s.energy,
        **_ENERGY,
    ),
    PduSensorDescription(
        key="temperature",
        translation_key="internal_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s.temperature,
    ),
    PduSensorDescription(
        key="humidity",
        translation_key="internal_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda s: s.humidity,
    ),
    PduSensorDescription(
        key="peak_current",
        translation_key="total_peak_current",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.peak_current,
        **_CURRENT,
    ),
    PduSensorDescription(
        key="peak_time",
        translation_key="total_peak_time",
        value_fn=lambda s: s.peak_time,
        **_PEAK_TIME,
    ),
    PduSensorDescription(
        key="warning_current",
        translation_key="total_warning_current",
        value_fn=lambda s: s.total_warning_current,
        **_LIMIT,
    ),
    PduSensorDescription(
        key="off_current",
        translation_key="total_off_current",
        value_fn=lambda s: s.total_off_current,
        **_LIMIT,
    ),
    *(
        PduSensorDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            suggested_display_precision=1,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=fn,
        )
        for key, fn in (
            ("voltage_min", lambda s: s.voltage_min),
            ("voltage_max", lambda s: s.voltage_max),
        )
    ),
    *(
        PduSensorDescription(
            key=key,
            translation_key=key,
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=0,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=fn,
        )
        for key, fn in (
            ("humidity_min", lambda s: s.humidity_min),
            ("humidity_max", lambda s: s.humidity_max),
        )
    ),
)

OUTLET_SENSORS: tuple[OutletSensorDescription, ...] = (
    OutletSensorDescription(
        key="current",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.current,
        **_CURRENT,
    ),
    OutletSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda o: o.power,
    ),
    OutletSensorDescription(
        key="apparent_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        suggested_display_precision=0,
        value_fn=lambda o: o.apparent_power,
    ),
    OutletSensorDescription(
        key="power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda o: o.power_factor,
    ),
    OutletSensorDescription(
        key="energy",
        value_fn=lambda o: o.energy,
        **_ENERGY,
    ),
    OutletSensorDescription(
        key="peak_current",
        translation_key="peak_current",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda o: o.peak_current,
        **_CURRENT,
    ),
    OutletSensorDescription(
        key="peak_time",
        translation_key="peak_time",
        value_fn=lambda o: o.peak_time,
        **_PEAK_TIME,
    ),
    OutletSensorDescription(
        key="warning_current",
        translation_key="warning_current",
        value_fn=lambda o: o.warning_current,
        **_LIMIT,
    ),
    OutletSensorDescription(
        key="off_current",
        translation_key="off_current",
        value_fn=lambda o: o.off_current,
        **_LIMIT,
    ),
    OutletSensorDescription(
        key="priority",
        translation_key="priority",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.priority,
    ),
    OutletSensorDescription(
        key="power_on_delay",
        translation_key="power_on_delay",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.power_on_delay,
    ),
)


@dataclass(frozen=True, kw_only=True)
class HttpSensorDescription(SensorEntityDescription):
    """Sensor fed by the web API; value_fn gets the outlet index (or None)."""

    value_fn: Callable[[HttpState, int | None], StateValue]


HTTP_OUTLET_SENSORS: tuple[HttpSensorDescription, ...] = (
    HttpSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        value_fn=lambda s, i: s.lifetime_energy[i] if i is not None else None,
        **_ENERGY,
    ),
    HttpSensorDescription(
        key="apparent_energy",
        translation_key="apparent_energy",
        native_unit_of_measurement="VAh",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda s, i: s.apparent_energy[i] if i is not None else None,
    ),
)

HTTP_PDU_SENSORS: tuple[HttpSensorDescription, ...] = (
    HttpSensorDescription(
        key="airflow",
        translation_key="airflow",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda s, _: s.airflow,
    ),
    HttpSensorDescription(
        key="device_time",
        translation_key="device_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s, _: s.device_time,
    ),
)


def _external_temperature(n: int, connected: bool) -> HttpSensorDescription:
    return HttpSensorDescription(
        key=f"external_temperature_{n + 1}",
        translation_key="external_temperature",
        translation_placeholders={"sensor": str(n + 1)},
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        # Probes are optional; only enable the ones plugged in at setup.
        entity_registry_enabled_default=connected,
        value_fn=lambda s, _: s.external_temperatures[n],
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DcmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up DCMU sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [PduSensor(coordinator, d) for d in PDU_SENSORS]
    entities += [
        OutletSensor(coordinator, d, i) for i in range(NUM_OUTLETS) for d in OUTLET_SENSORS
    ]
    if (http := coordinator.http) is not None:
        entities += [HttpSensor(http, d) for d in HTTP_PDU_SENSORS]
        temps = http.data.external_temperatures if http.data else [None] * NUM_OUTLETS
        entities += [
            HttpSensor(http, _external_temperature(n, temps[n] is not None))
            for n in range(NUM_OUTLETS)
        ]
        entities += [
            HttpSensor(http, d, i) for i in range(NUM_OUTLETS) for d in HTTP_OUTLET_SENSORS
        ]
    async_add_entities(entities)


class PduSensor(DcmuEntity, SensorEntity):
    """PDU-level sensor."""

    entity_description: PduSensorDescription

    @property
    def native_value(self) -> StateValue:
        return self.entity_description.value_fn(self.coordinator.data)


class OutletSensor(DcmuOutletEntity, SensorEntity):
    """Outlet-level sensor."""

    entity_description: OutletSensorDescription

    @property
    def native_value(self) -> StateValue:
        return self.entity_description.value_fn(self.outlet)


class HttpSensor(DcmuHttpEntity, SensorEntity):
    """Sensor fed by the web API."""

    entity_description: HttpSensorDescription

    @property
    def native_value(self) -> StateValue:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.index)
