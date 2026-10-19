"""Synthetic device data for tests.

Everything here is invented: no values, strings or memory bytes recorded from a
real device. Raw SNMP values and web API bytes are encoded from the same
made-up readings, so the tests check the decoding without shipping device
data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.racktivity_dcmu.pdu import BASE, NUM_OUTLETS
from custom_components.racktivity_dcmu.snmp import SnmpValue

PDU_NAME = "Test PDU"
RACK = "Test Rack"
OUTLET_NAMES = [f"Out{n}" for n in range(1, NUM_OUTLETS + 1)]
EVENT_IP = "192.0.2.50"  # RFC 5737 documentation range
SW_VERSION = (1, 23)
HW_VERSION = (4, 5)

VOLTAGE_CV = 23100  # 231.00 V
FREQUENCY_CHZ = 5000  # 50.00 Hz
TEMPERATURE_DC = 215  # 21.5 °C
TEMPERATURE_WARNING_DC = 450  # 45.0 °C
EXTERNAL_WARNING_DC = 700  # 70.0 °C
HUMIDITY_PCT = 40
RELAYS = [1, 1, 1, 1, 1, 0, 0, 0]
CURRENT_MA = [500, 0, 0, 0, 0, 0, 0, 0]
POWER_W = [100, 0, 0, 0, 0, 0, 0, 0]
APPARENT_VA = [115, 0, 0, 0, 0, 0, 0, 0]
PF_PCT = [87, 100, 100, 100, 100, 100, 100, 100]  # agent reports 100 when idle
ENERGY_WH = [10_000 + 1_111 * i for i in range(NUM_OUTLETS)]
LIFETIME_WH = [50_000 + 2_222 * i for i in range(NUM_OUTLETS)]
APPARENT_VAH = [20_000 + 333 * i for i in range(NUM_OUTLETS)]
PEAK_MA = [1_000 + 100 * i for i in range(NUM_OUTLETS)]
PEAK_TIME = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
DEVICE_TIME = int(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp())


def _scalar(n: int) -> str:
    return f"{BASE}.2.{n}.0"


def _col(col: int, i: int) -> str:
    return f"{BASE}.3.1.1.{col}.{i}"


def snmp_values() -> dict[str, SnmpValue]:
    """Every OID the integration reads, with invented values."""
    v: dict[str, SnmpValue] = {
        "1.3.6.1.2.1.1.1.0": b"DCMU",
        "1.3.6.1.2.1.1.2.0": BASE,
        "1.3.6.1.2.1.1.3.0": 12345,
        "1.3.6.1.2.1.1.5.0": b"test",
        f"{BASE}.1.1.0": b"DCMU_8port",
        f"{BASE}.1.2.0": b"v0.0",
        f"{BASE}.1.3.0": b"01/2000",
        _scalar(1): VOLTAGE_CV,
        _scalar(2): FREQUENCY_CHZ,
        _scalar(3): sum(CURRENT_MA),
        _scalar(4): sum(POWER_W),
        _scalar(5): TEMPERATURE_DC,
        _scalar(6): HUMIDITY_PCT,
        _scalar(7): 10_000,
        _scalar(8): 14_000,
        _scalar(9): 2_500,
        _scalar(10): PEAK_TIME,
        _scalar(11): sum(ENERGY_WH),
        _scalar(15): PDU_NAME.encode(),
        _scalar(16): RACK.encode(),
        _scalar(17): 20,  # 10 %
        _scalar(18): -96,  # signed byte 160 -> 80 %
        _scalar(20): 22000,
        _scalar(21): 24000,
        _scalar(22): 1,
    }
    for n in (12, 13, 14):
        v[_scalar(n)] = 0
    v[_scalar(19)] = 1  # humidity trap enable
    v[_scalar(23)] = TEMPERATURE_WARNING_DC
    v[_scalar(24)] = 1  # temperature trap enable
    for i in range(NUM_OUTLETS):
        v[_col(2, i)] = OUTLET_NAMES[i].encode()
        v[_col(3, i)] = CURRENT_MA[i]
        v[_col(4, i)] = POWER_W[i]
        v[_col(5, i)] = APPARENT_VA[i]
        v[_col(6, i)] = PF_PCT[i]
        v[_col(7, i)] = RELAYS[i]
        v[_col(8, i)] = ENERGY_WH[i]
        v[_col(9, i)] = 0
        v[_col(10, i)] = PEAK_MA[i]
        v[_col(11, i)] = PEAK_TIME
        v[_col(12, i)] = 2_000
        v[_col(13, i)] = 3_000
        v[_col(14, i)] = 1
        v[_col(15, i)] = i
        for col in (2, 3, 4):
            v[f"{BASE}.4.1.1.{col}.{i}"] = 0  # external probes: not connected
        v[f"{BASE}.4.1.1.5.{i}"] = EXTERNAL_WARNING_DC
        v[f"{BASE}.4.1.1.6.{i}"] = 1
    return v


def _u32(value: int) -> list[int]:
    return list(value.to_bytes(4, "little"))


def ram_32_96() -> list[int]:
    """Web API RAM bytes 32..127 for the invented readings."""
    ram = [0] * 96

    def put(addr: int, data: list[int]) -> None:
        ram[addr - 32 : addr - 32 + len(data)] = data

    for i in range(NUM_OUTLETS):
        put(32 + 4 * i, _u32(APPARENT_VAH[i]))
    # 112..119 external probes: 0 = not connected. 120/121 internal temp/humidity.
    put(120, [round((TEMPERATURE_DC / 10 + 32) * 2), HUMIDITY_PCT * 2])
    put(122, [0, 0])  # airflow 0.0 m/s, intrusion inputs off
    put(124, _u32(DEVICE_TIME))
    return ram


def flash_lifetime() -> list[int]:
    """Web API flash bytes 128..159: lifetime energy per outlet."""
    return [b for wh in LIFETIME_WH for b in _u32(wh)]


def flash_versions() -> list[int]:
    """Web API flash bytes 194..199."""
    return [*SW_VERSION, 0, 0, *HW_VERSION]


# Event log in the device's fixed-width layout, newest first. Four rows share
# the newest second, six the second before (like one settings-page save).
_EVENT_ROWS = [
    ("Fri Jan 02 03:04:05 2026", 562, 1),
    ("Fri Jan 02 03:04:05 2026", 561, 1),
    ("Fri Jan 02 03:04:05 2026", 560, 1),
    ("Fri Jan 02 03:04:05 2026", 202, 1),
    ("Fri Jan 02 03:04:04 2026", 32, 16),
    ("Fri Jan 02 03:04:04 2026", 32, 16),
    ("Fri Jan 02 03:04:04 2026", 16, 7),
    ("Fri Jan 02 03:04:04 2026", 576, 1),
    ("Fri Jan 02 03:04:04 2026", 577, 1),
    ("Fri Jan 02 03:04:04 2026", 624, 4),
]


def events_text(rows: int | None = None, skip: int = 0) -> str:
    """Event log response; skip drops the newest rows (older device state)."""
    header = (
        "                     timestamp,                             Description,"
        "                      Variable,      IP Address, Start address, Length, Irms[1] (A)"
    )
    lines = [header]
    for ts, addr, length in _EVENT_ROWS[skip : None if rows is None else skip + rows]:
        lines.append(
            f"{ts} (UTC),   I: setting changed through HTTP (112),"
            f"                             0,  {EVENT_IP:>14},{addr:>14},{length:>7},       0.500"
        )
    return "\n".join(lines)
