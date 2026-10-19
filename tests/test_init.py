"""Setup, entities, polling tiers, relay control and diagnostics."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.racktivity_dcmu.const import (
    CONF_COMMUNITY,
    CONF_CONFIG_INTERVAL,
    CONF_ENABLE_CONTROL,
    CONF_SCAN_INTERVAL,
    CONF_WRITE_COMMUNITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_RELAY_CHANGED,
)

from .conftest import HOST, READ_COMMUNITY, WRITE_COMMUNITY

BASE = "1.3.6.1.4.1.34097"
DATA = {CONF_HOST: HOST, CONF_PORT: 161, CONF_COMMUNITY: READ_COMMUNITY}


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=f"{HOST}:161", data=DATA, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_states(hass: HomeAssistant, fake_snmp) -> None:
    """Sensors carry SI values decoded from the recorded walk."""
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    voltage = hass.states.get("sensor.test_pdu_voltage")
    assert voltage is not None
    assert float(voltage.state) == pytest.approx(fake_snmp.values[f"{BASE}.2.1.0"] / 100)
    assert voltage.attributes["unit_of_measurement"] == "V"

    current = hass.states.get("sensor.test_pdu_out1_current")
    assert float(current.state) == pytest.approx(fake_snmp.values[f"{BASE}.3.1.1.3.0"] / 1000)

    energy = hass.states.get("sensor.test_pdu_out1_energy")
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"
    assert float(energy.state) == pytest.approx(
        fake_snmp.values[f"{BASE}.3.1.1.8.0"] / 1000, abs=1e-3
    )

    assert float(hass.states.get("sensor.test_pdu_internal_temperature").state) == 21.5

    # Read-only relay state by default; outlets 6-8 are off in the test data.
    assert hass.states.get("binary_sensor.test_pdu_out1").state == STATE_ON
    assert hass.states.get("binary_sensor.test_pdu_out6").state == STATE_OFF
    assert hass.states.get("switch.test_pdu_out1") is None

    # Limits are diagnostic and disabled by default.
    registry = er.async_get(hass)
    limit = registry.async_get("sensor.test_pdu_out1_current_warning_level")
    assert limit is not None and limit.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    assert all(not c.sets for c in fake_snmp.instances)


async def test_polling_tiers(
    hass: HomeAssistant, fake_snmp, freezer: FrozenDateTimeFactory
) -> None:
    """Config is not re-read every scan, but is after a relay change."""
    events = async_capture_events(hass, EVENT_RELAY_CHANGED)
    await _setup(hass)
    client = fake_snmp.instances[-1]
    pdu = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.pdu
    config_reads = 0
    orig = pdu.read_config

    async def counting_read_config():
        nonlocal config_reads
        config_reads += 1
        return await orig()

    pdu.read_config = counting_read_config

    for _ in range(3):
        freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert config_reads == 0
    gets_before = client.gets

    # Someone switches outlet 1 off at the PDU.
    fake_snmp.values[f"{BASE}.3.1.1.7.0"] = 0
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.test_pdu_out1").state == STATE_OFF
    assert config_reads == 1
    assert client.gets > gets_before
    assert len(events) == 1
    assert events[0].data["outlet"] == 1
    assert events[0].data["is_on"] is False


async def test_unavailable_when_offline(
    hass: HomeAssistant, fake_snmp, freezer: FrozenDateTimeFactory
) -> None:
    """Timeouts mark entities unavailable, and they recover."""
    await _setup(hass)
    fake_snmp.offline = True
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_pdu_voltage").state == STATE_UNAVAILABLE
    fake_snmp.offline = False
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_pdu_voltage").state != STATE_UNAVAILABLE


async def test_setup_retry_when_offline(hass: HomeAssistant, fake_snmp) -> None:
    """Unreachable at startup -> retry later."""
    fake_snmp.offline = True
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=DATA)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert fake_snmp.instances[-1].closed


async def test_control_needs_write_community(hass: HomeAssistant, fake_snmp) -> None:
    """The opt-in alone does not create switches."""
    await _setup(hass, {CONF_ENABLE_CONTROL: True})
    assert hass.states.get("switch.test_pdu_out1") is None
    assert hass.states.get("binary_sensor.test_pdu_out1") is not None


async def test_switch(hass: HomeAssistant, fake_snmp) -> None:
    """With control enabled, switching sends one SET and re-reads state."""
    entry = await _setup(hass, {CONF_ENABLE_CONTROL: True, CONF_WRITE_COMMUNITY: WRITE_COMMUNITY})
    assert hass.states.get("binary_sensor.test_pdu_out6") is None
    assert hass.states.get("switch.test_pdu_out6").state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.test_pdu_out6"}, blocking=True
    )
    client = entry.runtime_data.pdu.client
    assert client.sets == [(f"{BASE}.3.1.1.7.5", 1)]
    assert hass.states.get("switch.test_pdu_out6").state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.test_pdu_out6"}, blocking=True
    )
    assert client.sets[-1] == (f"{BASE}.3.1.1.7.5", 0)
    assert hass.states.get("switch.test_pdu_out6").state == STATE_OFF


async def test_switch_failure(hass: HomeAssistant, fake_snmp) -> None:
    """A rejected SET surfaces as an error, state unchanged."""
    from homeassistant.exceptions import HomeAssistantError

    await _setup(hass, {CONF_ENABLE_CONTROL: True, CONF_WRITE_COMMUNITY: "stale"})
    with pytest.raises(HomeAssistantError, match="Switching outlet 6 failed"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.test_pdu_out6"}, blocking=True
        )
    assert hass.states.get("switch.test_pdu_out6").state == STATE_OFF


async def test_toggling_control_cleans_registry(hass: HomeAssistant, fake_snmp) -> None:
    """Switching between switch and binary sensor leaves no orphans."""
    entry = await _setup(hass, {CONF_ENABLE_CONTROL: True, CONF_WRITE_COMMUNITY: WRITE_COMMUNITY})
    registry = er.async_get(hass)
    assert registry.async_get("switch.test_pdu_out1") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 5, CONF_CONFIG_INTERVAL: 300, CONF_ENABLE_CONTROL: False},
    )
    await hass.async_block_till_done()
    assert registry.async_get("switch.test_pdu_out1") is None
    assert hass.states.get("binary_sensor.test_pdu_out1").state == STATE_ON


async def test_unload(hass: HomeAssistant, fake_snmp) -> None:
    """Unload closes the socket."""
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert fake_snmp.instances[-1].closed


async def test_diagnostics(hass: HomeAssistant, hass_client, fake_snmp) -> None:
    """Communities are redacted; unidentified OIDs are listed."""
    entry = await _setup(hass, {CONF_ENABLE_CONTROL: True, CONF_WRITE_COMMUNITY: WRITE_COMMUNITY})
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diag["entry"]["data"][CONF_COMMUNITY] == "**REDACTED**"
    assert diag["entry"]["options"][CONF_WRITE_COMMUNITY] == "**REDACTED**"
    assert diag["state"]["name"] == "Test PDU"
    assert "2.23.0" in diag["unidentified_oids"]


async def test_power_factor_unknown_when_idle(hass: HomeAssistant, fake_snmp) -> None:
    """Idle outlets report PF 100 %; expose it as unknown instead."""
    await _setup(hass)
    assert float(hass.states.get("sensor.test_pdu_out1_power_factor").state) > 0
    assert hass.states.get("sensor.test_pdu_out2_power_factor").state == "unknown"


def _loaded_platforms(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    from homeassistant.helpers import entity_platform

    return {
        p.domain
        for p in entity_platform.async_get_platforms(hass, DOMAIN)
        if p.config_entry is not None and p.config_entry.entry_id == entry.entry_id
    }


async def test_options_change_unloads_old_platforms(hass: HomeAssistant, fake_snmp) -> None:
    """Enabling control replaces the binary sensor platform instead of leaking it."""
    entry = await _setup(hass)
    assert _loaded_platforms(hass, entry) == {"sensor", "binary_sensor"}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 5,
            CONF_CONFIG_INTERVAL: 300,
            CONF_ENABLE_CONTROL: True,
            CONF_WRITE_COMMUNITY: WRITE_COMMUNITY,
        },
    )
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _loaded_platforms(hass, entry) == {"sensor", "switch"}
    assert hass.states.get("switch.test_pdu_out1").state == STATE_ON
