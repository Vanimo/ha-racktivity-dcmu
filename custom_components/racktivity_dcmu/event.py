"""Device event log as an event entity (web API)."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DcmuConfigEntry
from .entity import DcmuHttpEntity

PARALLEL_UPDATES = 0

DEVICE_LOG = EventEntityDescription(
    key="device_log",
    translation_key="device_log",
    event_types=["info", "warning", "error", "other"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DcmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the device log event entity."""
    if (http := entry.runtime_data.http) is not None:
        async_add_entities([DeviceLogEvent(http, DEVICE_LOG)])


class DeviceLogEvent(DcmuHttpEntity, EventEntity):
    """Fires for each new row in the PDU's event log."""

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            for event in data.new_events:
                self._trigger_event(
                    event.level,
                    {
                        "description": event.description,
                        "setting": event.setting,
                        "address": event.address,
                        "length": event.length,
                        "ip_address": event.ip_address,
                        "device_timestamp": event.timestamp.isoformat(),
                    },
                )
        super()._handle_coordinator_update()
