"""Web API (read-only) client and its Home Assistant entities."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.racktivity_dcmu.const import (
    CONF_COMMUNITY,
    CONF_CONFIG_INTERVAL,
    CONF_HTTP_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    DOMAIN,
    EVENT_DEVICE_EVENT,
)
from custom_components.racktivity_dcmu.http_api import (
    DcmuHttpError,
    EventTracker,
    parse_array,
    parse_events,
    read_code,
)

from . import synthetic
from .conftest import HOST, READ_COMMUNITY

URL = f"http://{HOST}/Data.php"
DATA = {CONF_HOST: HOST, CONF_PORT: 161, CONF_COMMUNITY: READ_COMMUNITY}
WEB = {CONF_WEB_USERNAME: "admin", CONF_WEB_PASSWORD: "secret"}


def _array(var: str, values: list[int]) -> str:
    return f"var {var} = new Array({','.join(map(str, values))})"


def _mock_device(aioclient_mock: AiohttpClientMocker, events: str | None = None) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{URL}?code=GF00194000060000000001D", text=_array("D", synthetic.flash_versions())
    )
    aioclient_mock.get(f"{URL}?code=GR0003200096D", text=_array("D", synthetic.ram_32_96()))
    aioclient_mock.get(
        f"{URL}?code=GF00128000320000000001D", text=_array("D", synthetic.flash_lifetime())
    )
    aioclient_mock.get(f"{URL}?log=3&len=20", text=events or synthetic.events_text())


def _assert_only_reads(aioclient_mock: AiohttpClientMocker) -> None:
    for method, url, *_ in aioclient_mock.mock_calls:
        assert method == "GET"
        code = url.query.get("code")
        assert code is None or code.startswith(("GR", "GF")), url
        assert "log" in url.query or code is not None


# ----------------------------------------------------------------- unit tests


def test_read_code() -> None:
    assert read_code("R", 0, 217) == "GR0000000217D"
    assert read_code("F", 128, 32, "E") == "GF00128000320000000001E"


@pytest.mark.parametrize(
    ("area", "address", "length"),
    [
        ("F", 0, 1024),  # whole config block includes credentials
        ("F", 16, 1),  # web username
        ("F", 40, 16),  # web password
        ("F", 600, 4),  # SNMP communities
        ("F", 590, 4),  # overlaps read community
        ("S", 146, 1),  # not a read
        ("O", 146, 1),
        ("R", 1000, 100),  # out of range
    ],
)
def test_read_code_refuses(area: str, address: int, length: int) -> None:
    with pytest.raises(ValueError):
        read_code(area, address, length)


def test_parse_array() -> None:
    assert parse_array("var D = new Array(1,2,255)", 3) == [1, 2, 255]
    for bad in ("401 Unauthorized", "var D = new Array(1,2)", "var D = new Array(1,999,3)"):
        with pytest.raises(DcmuHttpError):
            parse_array(bad, 3)


def test_parse_events() -> None:
    events = parse_events(synthetic.events_text())
    assert len(events) == 10
    first = events[0]
    assert first.timestamp == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert first.level == "info"
    assert first.description == "setting changed through HTTP (112)"
    assert first.ip_address == synthetic.EVENT_IP
    assert first.address == 562
    assert first.setting == "long_term_log_interval"
    assert {e.setting for e in events} >= {"web_password", "web_username", "snmp_trap_ip"}


def test_event_tracker() -> None:
    events = parse_events(synthetic.events_text())  # newest first
    tracker = EventTracker()
    assert tracker.new(events[3:]) == []  # first read only primes
    fresh = tracker.new(events)
    # Oldest first: reverse of the device's newest-first order.
    assert fresh == events[2::-1]
    assert tracker.new(events) == []
    # Another event in the same second as the newest one.
    assert tracker.new([events[0], *events]) == [events[0]]


# ------------------------------------------------------------------ HA tests


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=DATA, options=WEB)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_http_entities(
    hass: HomeAssistant, fake_snmp, aioclient_mock: AiohttpClientMocker
) -> None:
    """Lifetime energy, versions and sensors come from the web API."""
    _mock_device(aioclient_mock)
    entry = await _setup(hass)

    lifetime = hass.states.get("sensor.test_pdu_out1_lifetime_energy")
    assert lifetime is not None
    assert float(lifetime.state) == pytest.approx(synthetic.LIFETIME_WH[0] / 1000)
    assert lifetime.attributes["state_class"] == "total_increasing"
    # Resettable counter (SNMP) still there, distinct from lifetime.
    assert hass.states.get("sensor.test_pdu_out1_energy") is not None

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device.sw_version == "1.23"
    assert device.hw_version == "4.05"

    # No probes connected in the fixture -> external temperatures disabled.
    assert hass.states.get("sensor.test_pdu_external_temperature_1") is None
    assert hass.states.get("event.test_pdu_device_log") is not None
    _assert_only_reads(aioclient_mock)


async def test_new_events(
    hass: HomeAssistant,
    fake_snmp,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """New log rows fire events and trigger an SNMP config re-read."""
    bus_events = async_capture_events(hass, EVENT_DEVICE_EVENT)
    _mock_device(aioclient_mock, synthetic.events_text(skip=4))
    entry = await _setup(hass)
    assert bus_events == []  # existing rows are not replayed at startup

    pdu = entry.runtime_data.pdu
    calls = 0
    orig = pdu.read_config

    async def counting():
        nonlocal calls
        calls += 1
        return await orig()

    pdu.read_config = counting

    _mock_device(aioclient_mock)  # four newer rows appear
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(bus_events) == 4
    assert bus_events[-1].data["setting"] == "long_term_log_interval"
    assert bus_events[-1].data["ip_address"] == synthetic.EVENT_IP
    state = hass.states.get("event.test_pdu_device_log")
    assert state.attributes["event_type"] == "info"
    assert state.attributes["setting"] == "long_term_log_interval"
    assert calls >= 1
    _assert_only_reads(aioclient_mock)


async def test_bad_web_login(
    hass: HomeAssistant, fake_snmp, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected web login only affects the web API entities."""
    aioclient_mock.get(f"{URL}?code=GF00194000060000000001D", status=401)
    entry = await _setup(hass)
    assert hass.states.get("sensor.test_pdu_voltage").state != STATE_UNAVAILABLE
    assert hass.states.get("sensor.test_pdu_out1_lifetime_energy").state == STATE_UNAVAILABLE
    assert entry.runtime_data.http is not None


async def test_options_web_login(
    hass: HomeAssistant, fake_snmp, aioclient_mock: AiohttpClientMocker
) -> None:
    """The options flow checks the web login with one read."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{HOST}:161", data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.get(f"{URL}?code=GF00194000060000000001D", status=401)
    base = {CONF_SCAN_INTERVAL: 5, CONF_CONFIG_INTERVAL: 300, CONF_HTTP_INTERVAL: 60}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**base, **WEB})
    assert result["errors"] == {"base": "invalid_auth"}

    _mock_device(aioclient_mock)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**base, **WEB})
    await hass.async_block_till_done()
    assert entry.options[CONF_WEB_USERNAME] == "admin"
    assert hass.states.get("sensor.test_pdu_out1_lifetime_energy") is not None
    _assert_only_reads(aioclient_mock)


async def test_diagnostics_redacts_web_login(
    hass: HomeAssistant, hass_client, fake_snmp, aioclient_mock: AiohttpClientMocker
) -> None:
    """Web login never ends up in diagnostics."""
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )

    _mock_device(aioclient_mock)
    entry = await _setup(hass)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diag["entry"]["options"][CONF_WEB_USERNAME] == "**REDACTED**"
    assert diag["entry"]["options"][CONF_WEB_PASSWORD] == "**REDACTED**"
    assert "secret" not in json.dumps(diag)
    assert diag["web_api"]["data"]["sw_version"] == "1.23"


async def test_removing_web_login_cleans_registry(
    hass: HomeAssistant, fake_snmp, aioclient_mock: AiohttpClientMocker
) -> None:
    """Web API entities are removed with the web login; SNMP ones stay."""
    from homeassistant.helpers import entity_registry as er

    _mock_device(aioclient_mock)
    entry = await _setup(hass)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.test_pdu_out1_lifetime_energy") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 5, CONF_CONFIG_INTERVAL: 300, CONF_HTTP_INTERVAL: 60},
    )
    await hass.async_block_till_done()
    assert CONF_WEB_USERNAME not in entry.options
    assert registry.async_get("sensor.test_pdu_out1_lifetime_energy") is None
    assert registry.async_get("event.test_pdu_device_log") is None
    assert registry.async_get("sensor.test_pdu_out1_energy") is not None
    assert hass.states.get("binary_sensor.test_pdu_out1") is not None
