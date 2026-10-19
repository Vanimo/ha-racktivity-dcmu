"""Racktivity DCMU (EnergySwitch PM0816) integration."""

from __future__ import annotations

import logging
import re

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_COMMUNITY,
    CONF_ENABLE_CONTROL,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    CONF_WRITE_COMMUNITY,
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
)
from .coordinator import DcmuConfigEntry, DcmuCoordinator, DcmuHttpCoordinator
from .entity import pdu_device_info
from .http_api import DcmuHttp
from .pdu import DcmuSnmp
from .snmp import SnmpClient, SnmpError

_LOGGER = logging.getLogger(__name__)


def control_enabled(entry: DcmuConfigEntry) -> bool:
    """Relay control needs both the opt-in and a write community."""
    return bool(entry.options.get(CONF_ENABLE_CONTROL) and entry.options.get(CONF_WRITE_COMMUNITY))


def http_enabled(entry: DcmuConfigEntry) -> bool:
    """The web API is used only when a web login is configured."""
    return bool(entry.options.get(CONF_WEB_USERNAME) and entry.options.get(CONF_WEB_PASSWORD))


def platforms_for(entry: DcmuConfigEntry) -> list[Platform]:
    """Platforms in use for this entry's options."""
    platforms = [Platform.SENSOR]
    if control_enabled(entry):
        platforms.append(Platform.SWITCH)
    if not control_enabled(entry) or http_enabled(entry):
        # Relay state while read-only; intrusion inputs from the web API.
        platforms.append(Platform.BINARY_SENSOR)
    if http_enabled(entry):
        platforms.append(Platform.EVENT)
    return platforms


async def async_setup_entry(hass: HomeAssistant, entry: DcmuConfigEntry) -> bool:
    """Set up a DCMU from a config entry."""
    client = SnmpClient(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY),
    )
    pdu = DcmuSnmp(
        client,
        entry.options.get(CONF_WRITE_COMMUNITY) if control_enabled(entry) else None,
    )
    try:
        await pdu.identify()
    except SnmpError as err:
        pdu.close()
        raise ConfigEntryNotReady(f"Cannot reach {entry.data[CONF_HOST]}: {err}") from err

    coordinator = DcmuCoordinator(hass, entry, pdu)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        pdu.close()
        raise
    entry.runtime_data = coordinator

    # The PDU device must exist before outlet devices can point to it.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **pdu_device_info(coordinator)
    )

    if http_enabled(entry):
        api = DcmuHttp(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.options[CONF_WEB_USERNAME],
            entry.options[CONF_WEB_PASSWORD],
        )
        coordinator.http = DcmuHttpCoordinator(hass, entry, api, coordinator)
        # Optional extras: a web API failure must not block the SNMP entities.
        await coordinator.http.async_refresh()
        if not coordinator.http.last_update_success:
            _LOGGER.warning(
                "Web API of %s failed (%s); its entities stay unavailable until it works",
                entry.data[CONF_HOST],
                coordinator.http.last_exception,
            )

    _remove_stale_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, platforms_for(entry))
    return True


# unique_id suffixes of entities that only exist with the web API enabled.
_HTTP_KEYS = re.compile(
    r"_(lifetime_energy|apparent_energy|airflow|device_time|device_log"
    r"|external_temperature_\d|intrusion_\d)$"
)


def _remove_stale_entities(hass: HomeAssistant, entry: DcmuConfigEntry) -> None:
    """Drop entities that the current options no longer provide.

    Relay state moves between switch and binary sensor with the control
    option; web API entities go away when the web login is removed.
    """
    inactive_relay = Platform.BINARY_SENSOR if control_enabled(entry) else Platform.SWITCH
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        stale_relay = reg_entry.domain == inactive_relay and reg_entry.unique_id.endswith("_relay")
        stale_http = not http_enabled(entry) and _HTTP_KEYS.search(reg_entry.unique_id)
        if stale_relay or stale_http:
            registry.async_remove(reg_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: DcmuConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms_for(entry))
    if unloaded:
        entry.runtime_data.pdu.close()
    return unloaded
