"""Read-only smoke test against a real DCMU.

Skipped unless DCMU_LIVE_HOST is set, e.g.:
    DCMU_LIVE_HOST=<pdu-ip> pytest tests/test_live.py -s
Set DCMU_LIVE_WEB_USER / DCMU_LIVE_WEB_PASSWORD to include the (read-only)
web API. No write community is configured, so nothing can be switched.

Unlike the synthetic tests, this one checks the decoded values against
physical plausibility, which is the only way to catch a wrong scale factor
or OID mapping without a MIB.
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
from custom_components.racktivity_dcmu.pdu import NUM_OUTLETS

LIVE_HOST = os.environ.get("DCMU_LIVE_HOST")

pytestmark = pytest.mark.skipif(not LIVE_HOST, reason="DCMU_LIVE_HOST not set")


async def test_live_read_only(hass: HomeAssistant, socket_enabled) -> None:
    """Set up against the real device and check the values are plausible."""
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
    assert not hass.states.async_entity_ids("button")

    coordinator = entry.runtime_data
    state = coordinator.data
    assert state.model == "DCMU_8port"
    assert state.voltage is not None and 180 <= state.voltage <= 260, state.voltage
    assert state.frequency is not None and 45 <= state.frequency <= 65, state.frequency
    assert state.temperature is not None and -10 <= state.temperature <= 70, state.temperature
    assert state.humidity is not None and 0 <= state.humidity <= 100, state.humidity
    assert state.voltage_min is not None and state.voltage_max is not None
    assert 150 <= state.voltage_min < state.voltage_max <= 280
    assert state.temperature_warning is not None and 20 <= state.temperature_warning <= 90
    assert state.sensors_available is True
    assert len(state.outlets) == NUM_OUTLETS
    for outlet in state.outlets:
        assert outlet.name, outlet
        assert outlet.is_on is not None
        assert outlet.current is not None and 0 <= outlet.current <= 20, outlet
        assert outlet.power is not None and 0 <= outlet.power <= 5000, outlet
        assert outlet.energy is not None and outlet.energy >= 0
        assert outlet.warning_current is not None and 0 < outlet.warning_current <= 20
        assert outlet.off_current is not None and outlet.warning_current <= outlet.off_current
        if not outlet.is_on:
            assert outlet.current == 0 and outlet.power == 0, outlet
    assert (
        state.current is not None
        and abs(state.current - sum(o.current for o in state.outlets)) < 0.1
    )

    # Counters never go backwards between two polls.
    before = [o.energy for o in state.outlets]
    await coordinator.async_refresh()
    after = [o.energy for o in coordinator.data.outlets]
    assert all(b <= a for b, a in zip(before, after, strict=True)), (before, after)

    http = coordinator.http
    if http is not None:
        assert http.last_update_success, http.last_exception
        assert http.data.sw_version and http.data.hw_version
        assert all(e is not None and e >= 0 for e in http.data.lifetime_energy)
        assert all(
            (o.energy or 0) <= (lifetime or 0)
            for o, lifetime in zip(state.outlets, http.data.lifetime_energy, strict=True)
        ), "resettable counter above lifetime counter"

    registry = er.async_get(hass)
    for reg in sorted(
        er.async_entries_for_config_entry(registry, entry.entry_id), key=lambda r: r.entity_id
    ):
        st = hass.states.get(reg.entity_id)
        shown = (
            "(disabled)"
            if st is None
            else f"{st.state} {st.attributes.get('unit_of_measurement', '')}"
        )
        print(f"{reg.entity_id:60} {shown}")

    assert await hass.config_entries.async_unload(entry.entry_id)
