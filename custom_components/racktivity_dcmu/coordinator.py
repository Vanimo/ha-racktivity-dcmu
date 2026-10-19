"""Polling coordinators for the Racktivity DCMU.

SNMP coordinator, two tiers:
- live values (measurements + relay states) every scan interval;
- configuration (names, thresholds, peaks) every config interval, and
  immediately after a relay state change, our own write, or a
  "setting changed" entry in the device event log.

Optional HTTP coordinator (web login configured): values SNMP lacks, plus
the event log, on its own slower interval so a web API problem never
affects the SNMP entities.
"""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CONFIG_INTERVAL,
    CONF_HTTP_INTERVAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONFIG_INTERVAL,
    DEFAULT_HTTP_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DEVICE_EVENT,
    EVENT_RELAY_CHANGED,
)
from .http_api import DcmuHttp, DcmuHttpError, HttpState
from .pdu import DcmuSnmp, PduState
from .snmp import SnmpError

_LOGGER = logging.getLogger(__name__)

type DcmuConfigEntry = ConfigEntry[DcmuCoordinator]


class DcmuCoordinator(DataUpdateCoordinator[PduState]):
    """Fetch DCMU state over SNMP."""

    config_entry: DcmuConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DcmuConfigEntry, pdu: DcmuSnmp) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            # Entities only need a write when something changed.
            always_update=False,
        )
        self.pdu = pdu
        self.http: DcmuHttpCoordinator | None = None
        self.platforms: list[Platform] = []
        self.config_interval = entry.options.get(CONF_CONFIG_INTERVAL, DEFAULT_CONFIG_INTERVAL)
        self._config_due = 0.0  # monotonic; 0 = read on first refresh
        self._last_relay_mask: int | None = None
        self._sensors_warned = False

    async def _read_optional_sensors(self) -> None:
        """The sensor table is optional; log once if this firmware lacks it."""
        try:
            await self.pdu.read_sensors()
        except SnmpError as err:
            if self._sensors_warned is False:
                _LOGGER.info("Sensor table not readable on %s (%s)", self.pdu.client.host, err)
                self._sensors_warned = True

    def request_config_refresh(self) -> None:
        """Re-read configuration on the next update."""
        self._config_due = 0.0

    async def _async_update_data(self) -> PduState:
        try:
            state = await self.pdu.read_live()
            relay_changed = (
                self._last_relay_mask is not None and state.relay_mask != self._last_relay_mask
            )
            if relay_changed or time.monotonic() >= self._config_due:
                await self.pdu.read_config()
                self._config_due = time.monotonic() + self.config_interval
                await self._read_optional_sensors()
        except SnmpError as err:
            raise UpdateFailed(f"Error communicating with {self.pdu.client.host}: {err}") from err

        if relay_changed:
            assert self._last_relay_mask is not None
            changed = state.relay_mask ^ self._last_relay_mask
            for outlet in state.outlets:
                if changed & (1 << outlet.index):
                    self.hass.bus.async_fire(
                        EVENT_RELAY_CHANGED,
                        {
                            "config_entry_id": self.config_entry.entry_id,
                            "outlet": outlet.number,
                            "name": outlet.name,
                            "is_on": outlet.is_on,
                        },
                    )
        self._last_relay_mask = state.relay_mask
        # The state object is mutated in place; hand out a copy so
        # always_update=False can compare it with the previous one.
        return deepcopy(state)


class DcmuHttpCoordinator(DataUpdateCoordinator[HttpState]):
    """Fetch web-API-only values and new event log entries."""

    config_entry: DcmuConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DcmuConfigEntry,
        api: DcmuHttp,
        snmp: DcmuCoordinator,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_http",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_HTTP_INTERVAL, DEFAULT_HTTP_INTERVAL)
            ),
        )
        self.api = api
        self.snmp = snmp
        self._state = HttpState()

    async def _async_update_data(self) -> HttpState:
        had_versions = self._state.sw_version is not None
        try:
            state = await self.api.read_state(self._state)
        except DcmuHttpError as err:
            raise UpdateFailed(f"Web API error: {err}") from err

        if not had_versions and state.sw_version:
            self._update_device_versions(state)

        for event in state.new_events:
            self.hass.bus.async_fire(
                EVENT_DEVICE_EVENT,
                {
                    "config_entry_id": self.config_entry.entry_id,
                    "timestamp": event.timestamp.isoformat(),
                    "level": event.level,
                    "description": event.description,
                    "setting": event.setting,
                    "address": event.address,
                    "length": event.length,
                    "ip_address": event.ip_address,
                },
            )
        if any(e.setting for e in state.new_events) and self.snmp.last_update_success:
            # Someone changed a setting: re-read names/limits without waiting.
            self.snmp.request_config_refresh()
            await self.snmp.async_request_refresh()
        return deepcopy(state)

    def _update_device_versions(self, state: HttpState) -> None:
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self.config_entry.entry_id)
        if hasattr(registry, "async_get_device_by_identifier"):  # HA >= 2026.x
            device = registry.async_get_device_by_identifier(identifier, identifier[1])
        else:  # pragma: no cover
            device = registry.async_get_device(identifiers={identifier})
        if device is not None:
            registry.async_update_device(
                device.id, sw_version=state.sw_version, hw_version=state.hw_version
            )
