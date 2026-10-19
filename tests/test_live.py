"""Read-only smoke test against a real DCMU.

Skipped unless DCMU_LIVE_HOST is set, e.g.:
    DCMU_LIVE_HOST=<pdu-ip> pytest tests/test_live.py -s
Set DCMU_LIVE_WEB_USER / DCMU_LIVE_WEB_PASSWORD to include the (read-only)
web API. No write community is configured, so nothing can be switched.
"""

from __future__ import annotations

import os

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.racktivity_dcmu.const import (
    CONF_COMMUNITY,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    DOMAIN,
)

LIVE_HOST = os.environ.get("DCMU_LIVE_HOST")

pytestmark = pytest.mark.skipif(not LIVE_HOST, reason="DCMU_LIVE_HOST not set")


async def test_live_read_only(hass: HomeAssistant, socket_enabled) -> None:
    """Set up against the real device and print every entity state."""
    # The HA test plugin pins connections to localhost; allow the PDU.
    pytest_socket.socket_allow_hosts(["127.0.0.1", LIVE_HOST], allow_unix_socket=True)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: LIVE_HOST,
            CONF_PORT: 161,
            CONF_COMMUNITY: os.environ.get("DCMU_LIVE_COMMUNITY", "public"),
        },
        options=(
            {
                CONF_WEB_USERNAME: os.environ["DCMU_LIVE_WEB_USER"],
                CONF_WEB_PASSWORD: os.environ["DCMU_LIVE_WEB_PASSWORD"],
            }
            if os.environ.get("DCMU_LIVE_WEB_USER")
            else {}
        ),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert not hass.states.async_entity_ids("switch")
    http = entry.runtime_data.http
    if http is not None:
        print("web API ok:", http.last_update_success, http.last_exception or "")

    registry = er.async_get(hass)
    for reg in sorted(
        er.async_entries_for_config_entry(registry, entry.entry_id), key=lambda r: r.entity_id
    ):
        state = hass.states.get(reg.entity_id)
        shown = (
            "(disabled)"
            if state is None
            else f"{state.state} {state.attributes.get('unit_of_measurement', '')}"
        )
        print(f"{reg.entity_id:60} {shown}")

    assert await hass.config_entries.async_unload(entry.entry_id)
