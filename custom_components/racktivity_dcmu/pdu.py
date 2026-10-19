"""Racktivity DCMU (PM0816) data model over SNMP.

The agent has no published MIB; the meaning of each OID was derived from the
web UI and value comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .snmp import NoSuchObject, SnmpClient, SnmpValue

BASE = "1.3.6.1.4.1.34097"
NUM_OUTLETS = 8

SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"

OID_MODEL = f"{BASE}.1.1.0"
OID_AGENT_VERSION = f"{BASE}.1.2.0"
OID_AGENT_DATE = f"{BASE}.1.3.0"


def _scalar(n: int) -> str:
    return f"{BASE}.2.{n}.0"


def _outlet(col: int, idx: int) -> str:
    return f"{BASE}.3.1.1.{col}.{idx}"


def _outlet2(col: int, idx: int) -> str:
    return f"{BASE}.4.1.1.{col}.{idx}"


# PDU-level scalars (.2.x)
S_VOLTAGE = 1  # 0.01 V
S_FREQUENCY = 2  # 0.01 Hz
S_CURRENT = 3  # mA
S_POWER = 4  # W
S_TEMPERATURE = 5  # 0.1 °C (internal)
S_HUMIDITY = 6  # % (internal)
S_TOTAL_WARNING = 7  # mA
S_TOTAL_OFF = 8  # mA
S_PEAK_CURRENT = 9  # mA
S_PEAK_TIME = 10  # unix
S_ENERGY = 11  # Wh (sum of resettable outlet counters)
S_NAME = 15
S_RACK = 16
S_HUMIDITY_MIN = 17  # raw, /2 -> %
S_HUMIDITY_MAX = 18  # raw signed byte, (&0xFF)/2 -> %
S_VOLTAGE_MIN = 20  # 0.01 V
S_VOLTAGE_MAX = 21  # 0.01 V
S_VOLTAGE_TRAP = 22
S_UNKNOWN = (12, 13, 14, 19, 23, 24)

# Outlet table columns (.3.1.1.col.idx)
C_NAME = 2
C_CURRENT = 3  # mA
C_POWER = 4  # W
C_APPARENT = 5  # VA
C_PF = 6  # %
C_RELAY = 7  # 1 = on
C_ENERGY = 8  # Wh (resettable)
C_UNKNOWN9 = 9
C_PEAK_CURRENT = 10  # mA
C_PEAK_TIME = 11  # unix
C_WARNING = 12  # mA
C_OFF = 13  # mA
C_PRIORITY = 14
C_DELAY = 15

LIVE_SCALARS = (S_VOLTAGE, S_FREQUENCY, S_CURRENT, S_POWER, S_TEMPERATURE, S_HUMIDITY, S_ENERGY)
LIVE_COLUMNS = (C_CURRENT, C_POWER, C_APPARENT, C_PF, C_RELAY, C_ENERGY)
CONFIG_SCALARS = (
    S_TOTAL_WARNING,
    S_TOTAL_OFF,
    S_PEAK_CURRENT,
    S_PEAK_TIME,
    S_NAME,
    S_RACK,
    S_HUMIDITY_MIN,
    S_HUMIDITY_MAX,
    S_VOLTAGE_MIN,
    S_VOLTAGE_MAX,
    S_VOLTAGE_TRAP,
    *S_UNKNOWN,
)
CONFIG_COLUMNS = (
    C_NAME,
    C_UNKNOWN9,
    C_PEAK_CURRENT,
    C_PEAK_TIME,
    C_WARNING,
    C_OFF,
    C_PRIORITY,
    C_DELAY,
)
OUTLET2_COLUMNS = (2, 3, 4, 5, 6)

LIVE_OIDS: tuple[str, ...] = (
    *(_scalar(s) for s in LIVE_SCALARS),
    *(_outlet(c, i) for c in LIVE_COLUMNS for i in range(NUM_OUTLETS)),
)
CONFIG_OIDS: tuple[str, ...] = (
    OID_MODEL,
    OID_AGENT_VERSION,
    OID_AGENT_DATE,
    *(_scalar(s) for s in CONFIG_SCALARS),
    *(_outlet(c, i) for c in CONFIG_COLUMNS for i in range(NUM_OUTLETS)),
    *(_outlet2(c, i) for c in OUTLET2_COLUMNS for i in range(NUM_OUTLETS)),
)


class NotADcmu(Exception):
    """The agent does not look like a Racktivity DCMU."""


def _int(value: SnmpValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: SnmpValue) -> str | None:
    if isinstance(value, bytes):
        return value.split(b"\0", 1)[0].decode("latin-1").strip()
    if isinstance(value, str):
        return value
    return None


def _scaled(value: SnmpValue, div: float) -> float | None:
    raw = _int(value)
    return None if raw is None else raw / div


def _timestamp(value: SnmpValue) -> datetime | None:
    raw = _int(value)
    if not raw or raw < 0:
        return None
    return datetime.fromtimestamp(raw, UTC)


@dataclass(slots=True)
class Outlet:
    """One outlet. Electrical values are in SI units (A, W, VA, %, Wh)."""

    index: int
    name: str | None = None
    current: float | None = None
    power: float | None = None
    apparent_power: float | None = None
    power_factor: float | None = None
    is_on: bool | None = None
    energy: int | None = None
    peak_current: float | None = None
    peak_time: datetime | None = None
    warning_current: float | None = None
    off_current: float | None = None
    priority: int | None = None
    power_on_delay: int | None = None

    @property
    def number(self) -> int:
        """1-based outlet number as printed on the device."""
        return self.index + 1


@dataclass(slots=True)
class PduState:
    """Snapshot of everything read over SNMP."""

    model: str | None = None
    agent_version: str | None = None
    agent_date: str | None = None
    name: str | None = None
    rack_position: str | None = None
    voltage: float | None = None
    frequency: float | None = None
    current: float | None = None
    power: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    energy: int | None = None
    total_warning_current: float | None = None
    total_off_current: float | None = None
    peak_current: float | None = None
    peak_time: datetime | None = None
    humidity_min: float | None = None
    humidity_max: float | None = None
    voltage_min: float | None = None
    voltage_max: float | None = None
    voltage_trap: bool | None = None
    outlets: list[Outlet] = field(default_factory=lambda: [Outlet(i) for i in range(NUM_OUTLETS)])
    unknown: dict[str, SnmpValue] = field(default_factory=dict)
    live_updated: datetime | None = field(default=None, compare=False)
    config_updated: datetime | None = field(default=None, compare=False)

    @property
    def relay_mask(self) -> int:
        """Relay states as a bitmask, bit i = outlet i+1 (unknown counts as off)."""
        return sum(1 << o.index for o in self.outlets if o.is_on)


def apply_live(state: PduState, values: dict[str, SnmpValue]) -> None:
    """Update the live part of state from a GET of LIVE_OIDS."""

    def sv(n: int) -> SnmpValue:
        return values.get(_scalar(n))

    def ov(col: int, idx: int) -> SnmpValue:
        return values.get(_outlet(col, idx))

    state.voltage = _scaled(sv(S_VOLTAGE), 100)
    state.frequency = _scaled(sv(S_FREQUENCY), 100)
    state.current = _scaled(sv(S_CURRENT), 1000)
    state.power = _scaled(sv(S_POWER), 1)
    state.temperature = _scaled(sv(S_TEMPERATURE), 10)
    state.humidity = _scaled(sv(S_HUMIDITY), 1)
    state.energy = _int(sv(S_ENERGY))
    for outlet in state.outlets:
        i = outlet.index
        outlet.current = _scaled(ov(C_CURRENT, i), 1000)
        outlet.power = _scaled(ov(C_POWER, i), 1)
        outlet.apparent_power = _scaled(ov(C_APPARENT, i), 1)
        # The agent reports 100 % for an idle outlet; that's not a measurement.
        outlet.power_factor = _scaled(ov(C_PF, i), 1) if outlet.apparent_power else None
        relay = _int(ov(C_RELAY, i))
        outlet.is_on = None if relay is None else relay != 0
        outlet.energy = _int(ov(C_ENERGY, i))
    state.live_updated = datetime.now(UTC)


def apply_config(state: PduState, values: dict[str, SnmpValue]) -> None:
    """Update the configuration part of state from a GET of CONFIG_OIDS."""

    def sv(n: int) -> SnmpValue:
        return values.get(_scalar(n))

    def ov(col: int, idx: int) -> SnmpValue:
        return values.get(_outlet(col, idx))

    state.model = _str(values.get(OID_MODEL))
    state.agent_version = _str(values.get(OID_AGENT_VERSION))
    state.agent_date = _str(values.get(OID_AGENT_DATE))
    state.name = _str(sv(S_NAME))
    state.rack_position = _str(sv(S_RACK))
    state.total_warning_current = _scaled(sv(S_TOTAL_WARNING), 1000)
    state.total_off_current = _scaled(sv(S_TOTAL_OFF), 1000)
    state.peak_current = _scaled(sv(S_PEAK_CURRENT), 1000)
    state.peak_time = _timestamp(sv(S_PEAK_TIME))
    hmin, hmax = _int(sv(S_HUMIDITY_MIN)), _int(sv(S_HUMIDITY_MAX))
    state.humidity_min = None if hmin is None else (hmin & 0xFF) / 2
    state.humidity_max = None if hmax is None else (hmax & 0xFF) / 2
    state.voltage_min = _scaled(sv(S_VOLTAGE_MIN), 100)
    state.voltage_max = _scaled(sv(S_VOLTAGE_MAX), 100)
    trap = _int(sv(S_VOLTAGE_TRAP))
    state.voltage_trap = None if trap is None else bool(trap)
    for outlet in state.outlets:
        i = outlet.index
        outlet.name = _str(ov(C_NAME, i))
        outlet.peak_current = _scaled(ov(C_PEAK_CURRENT, i), 1000)
        outlet.peak_time = _timestamp(ov(C_PEAK_TIME, i))
        outlet.warning_current = _scaled(ov(C_WARNING, i), 1000)
        outlet.off_current = _scaled(ov(C_OFF, i), 1000)
        outlet.priority = _int(ov(C_PRIORITY, i))
        outlet.power_on_delay = _int(ov(C_DELAY, i))
    unknown_oids = [
        *(_scalar(s) for s in S_UNKNOWN),
        *(_outlet(C_UNKNOWN9, i) for i in range(NUM_OUTLETS)),
        *(_outlet2(c, i) for c in OUTLET2_COLUMNS for i in range(NUM_OUTLETS)),
    ]
    state.unknown = {
        oid[len(BASE) + 1 :]: values[oid]
        for oid in unknown_oids
        if oid in values and not isinstance(values[oid], NoSuchObject)
    }
    state.config_updated = datetime.now(UTC)


class DcmuSnmp:
    """High-level SNMP access to one DCMU."""

    def __init__(self, client: SnmpClient, write_community: str | None = None) -> None:
        self.client = client
        self.write_community = write_community or None
        self.state = PduState()

    @property
    def can_write(self) -> bool:
        """True when a write community is configured."""
        return self.write_community is not None

    async def identify(self) -> str:
        """Check the agent is a Racktivity DCMU, return its model string."""
        values = await self.client.get([SYS_OBJECT_ID, OID_MODEL])
        sys_oid = values.get(SYS_OBJECT_ID)
        model = _str(values.get(OID_MODEL))
        if not (isinstance(sys_oid, str) and sys_oid.startswith(BASE)) or not model:
            raise NotADcmu(f"sysObjectID={sys_oid!r} model={model!r}")
        return model

    async def read_live(self) -> PduState:
        """Read measurements and relay states."""
        apply_live(self.state, await self.client.get(LIVE_OIDS))
        return self.state

    async def read_config(self) -> PduState:
        """Read names, thresholds, peaks and the unidentified OIDs."""
        apply_config(self.state, await self.client.get(CONFIG_OIDS))
        return self.state

    async def set_relay(self, index: int, on: bool) -> None:
        """Switch one outlet relay via SNMP SET.

        Unverified on hardware: assumes .3.1.1.7.<index> is writable with
        1 = on / 0 = off.
        """
        if self.write_community is None:
            raise PermissionError("No SNMP write community configured")
        if not 0 <= index < NUM_OUTLETS:
            raise ValueError(f"Outlet index out of range: {index}")
        await self.client.set([(_outlet(C_RELAY, index), 1 if on else 0)], self.write_community)

    def close(self) -> None:
        """Release the socket."""
        self.client.close()
