"""Config and options flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.racktivity_dcmu.const import (
    CONF_COMMUNITY,
    CONF_CONFIG_INTERVAL,
    CONF_ENABLE_CONTROL,
    CONF_HTTP_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_WRITE_COMMUNITY,
    DOMAIN,
)

from .conftest import HOST, READ_COMMUNITY, WRITE_COMMUNITY

USER_INPUT = {CONF_HOST: HOST, CONF_PORT: 161, CONF_COMMUNITY: READ_COMMUNITY}


async def test_user_flow(hass: HomeAssistant, fake_snmp) -> None:
    """Happy path: entry titled after the PDU name."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test PDU"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == f"{HOST}:161"
    # No writes during setup.
    assert all(not c.sets for c in fake_snmp.instances)


async def test_user_flow_cannot_connect(hass: HomeAssistant, fake_snmp) -> None:
    """Wrong community looks like a timeout to SNMP."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_COMMUNITY: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    # Recovers once fixed.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_not_dcmu(hass: HomeAssistant, fake_snmp) -> None:
    """Some other SNMP device."""
    fake_snmp.values["1.3.6.1.2.1.1.2.0"] = "1.3.6.1.4.1.8072.3.2.10"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "not_dcmu"}


async def test_user_flow_already_configured(hass: HomeAssistant, fake_snmp) -> None:
    """Same host:port twice."""
    MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, fake_snmp) -> None:
    """Host can be changed."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.0.2.11"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_HOST] == "192.0.2.11"
    assert entry.unique_id == "192.0.2.11:161"


async def test_options_flow(hass: HomeAssistant, fake_snmp) -> None:
    """Control stays off without a write community."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 10.0, CONF_CONFIG_INTERVAL: 600.0, CONF_ENABLE_CONTROL: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        CONF_SCAN_INTERVAL: 10,
        CONF_CONFIG_INTERVAL: 600,
        CONF_ENABLE_CONTROL: False,
        CONF_HTTP_INTERVAL: 60,
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 5,
            CONF_CONFIG_INTERVAL: 300,
            CONF_ENABLE_CONTROL: True,
            CONF_WRITE_COMMUNITY: WRITE_COMMUNITY,
        },
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_ENABLE_CONTROL] is True
    assert entry.options[CONF_WRITE_COMMUNITY] == WRITE_COMMUNITY
    # Reloaded with switches instead of binary sensors.
    assert hass.states.get("switch.test_pdu_out1") is not None
