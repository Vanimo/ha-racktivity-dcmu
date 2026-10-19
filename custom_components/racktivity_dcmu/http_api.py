"""Read-only access to the DCMU web API (/Data.php), for values SNMP lacks.

Only memory reads (G codes) and log reads are implemented. There is no way
to build a write request with this module, and flash ranges holding the
web login or SNMP communities are refused.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import aiohttp

from .pdu import NUM_OUTLETS

# Flash ranges that hold credentials: web username+password, SNMP communities.
_SECRET_FLASH = ((16, 48), (592, 624))

# Live RAM block 32..127: resettable VAh, ..., sensors (112..123), clock (124).
_RAM_BLOCK = (32, 96)
# Flash: lifetime active energy per outlet.
_FLASH_LIFETIME = (128, 32)
# Flash: SW version (194,195), 196-197 unused, HW version (198,199).
_FLASH_VERSIONS = (194, 6)

_ARRAY_RE = re.compile(r"Array\(([^)]*)\)")
_TS_FORMAT = "%a %b %d %H:%M:%S %Y"

# Flash addresses that show up in "setting changed" events.
SETTING_NAMES: dict[int, str] = {
    0: "pdu_name",
    16: "web_username",
    32: "web_password",
    176: "rack_position",
    202: "time_flags",
    208: "outlet_priority",
    224: "outlet_power_on_delay",
    400: "outlet_off_level",
    416: "outlet_warning_level",
    480: "voltage_limits",
    496: "total_current_limits",
    560: "short_term_log_interval",
    561: "medium_term_log_interval",
    562: "long_term_log_interval",
    576: "oled_brightness",
    577: "oled_timeout",
    587: "snmp_trap_enable",
    589: "snmp_write_protection",
    590: "snmp_trap_port",
    592: "snmp_read_community",
    608: "snmp_write_community",
    624: "snmp_trap_ip",
    768: "ip_address",
    784: "netmask",
    800: "gateway",
    816: "dns_server",
    864: "dhcp",
    872: "ntp_server",
    880: "serial_baudrate",
    896: "serial_telnet_port",
    920: "serial_reset",
    976: "schedule",
}
SETTING_NAMES.update({48 + 16 * i: f"outlet_{i + 1}_name" for i in range(NUM_OUTLETS)})


class DcmuHttpError(Exception):
    """Web API request failed."""


class DcmuHttpAuthError(DcmuHttpError):
    """Web login rejected (HTTP 401)."""


@dataclass(slots=True, frozen=True)
class DeviceEvent:
    """One row of the device event log."""

    timestamp: datetime
    level: str  # info / warning / error / other
    description: str
    variable: str
    ip_address: str
    address: int | None
    length: int | None

    @property
    def setting(self) -> str | None:
        """Name of the changed setting, for 'setting changed' events."""
        if "setting changed" not in self.description or self.address is None:
            return None
        return SETTING_NAMES.get(self.address, f"address_{self.address}")


@dataclass(slots=True)
class HttpState:
    """Values read from the web API."""

    sw_version: str | None = None
    hw_version: str | None = None
    lifetime_energy: list[int | None] = field(default_factory=lambda: [None] * NUM_OUTLETS)
    apparent_energy: list[int | None] = field(default_factory=lambda: [None] * NUM_OUTLETS)
    external_temperatures: list[float | None] = field(default_factory=lambda: [None] * NUM_OUTLETS)
    airflow: float | None = None
    intrusion: tuple[bool, bool] | None = None
    device_time: datetime | None = None
    new_events: list[DeviceEvent] = field(default_factory=list)


def read_code(area: str, address: int, length: int, var: str = "D") -> str:
    """Build a Data.php read code. The only request type this module can make."""
    if area not in ("R", "F"):
        raise ValueError(f"Unknown memory area {area!r}")
    if not (0 <= address < 1024 and 0 < length <= 1024 - address):
        raise ValueError(f"Bad range {address}+{length}")
    if not var.isalpha() or len(var) != 1:
        raise ValueError(f"Bad variable name {var!r}")
    if area == "F":
        for lo, hi in _SECRET_FLASH:
            if address < hi and lo < address + length:
                raise ValueError(f"Refusing to read credential range {lo}..{hi - 1}")
        return f"GF{address:05d}{length:05d}0000000001{var}"
    return f"GR{address:05d}{length:05d}{var}"


def parse_array(text: str, length: int) -> list[int]:
    """Parse 'var D = new Array(1,2,...)'."""
    match = _ARRAY_RE.search(text)
    if not match:
        raise DcmuHttpError(f"Unexpected response: {text[:80]!r}")
    try:
        values = [int(v) for v in match.group(1).split(",") if v.strip()]
    except ValueError as err:
        raise DcmuHttpError(f"Bad array: {err}") from err
    if len(values) != length or any(not 0 <= v <= 255 for v in values):
        raise DcmuHttpError(f"Expected {length} bytes, got {len(values)}")
    return values


def _u32(b: list[int], p: int) -> int:
    return b[p] | b[p + 1] << 8 | b[p + 2] << 16 | b[p + 3] << 24


def _temp(raw: int) -> float | None:
    return None if raw in (0, 255) else raw / 2 - 32


def parse_events(text: str) -> list[DeviceEvent]:
    """Parse the event log (log=3), newest first as the device returns it."""
    events: list[DeviceEvent] = []
    for line in text.splitlines()[1:]:
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 6:
            continue
        try:
            ts = datetime.strptime(cols[0].removesuffix("(UTC)").strip(), _TS_FORMAT)
        except ValueError:
            continue
        desc = cols[1]
        level = {"I": "info", "W": "warning", "E": "error"}.get(desc[:1], "other")
        if desc[1:3] == ": ":
            desc = desc[3:]
        events.append(
            DeviceEvent(
                timestamp=ts.replace(tzinfo=UTC),
                level=level,
                description=desc,
                variable=cols[2],
                ip_address=cols[3],
                address=int(cols[4]) if cols[4].isdigit() else None,
                length=int(cols[5]) if cols[5].isdigit() else None,
            )
        )
    return events


class EventTracker:
    """Pick out events not seen before from successive newest-first log reads."""

    def __init__(self) -> None:
        self._last: datetime | None = None
        self._count_at_last = 0

    def new(self, events: list[DeviceEvent]) -> list[DeviceEvent]:
        """Return unseen events, oldest first. The first call only primes."""
        if not events:
            return []
        newest = events[0].timestamp
        at_newest = sum(1 for e in events if e.timestamp == newest)
        if self._last is None:
            fresh: list[DeviceEvent] = []
        else:
            fresh = [e for e in events if e.timestamp > self._last]
            same = [e for e in events if e.timestamp == self._last]
            if len(same) > self._count_at_last:
                fresh += same[: len(same) - self._count_at_last]
        if self._last is None or newest > self._last:
            self._last, self._count_at_last = newest, at_newest
        elif newest == self._last:
            self._count_at_last = max(self._count_at_last, at_newest)
        # Device order is newest first (also within one second).
        return fresh[::-1]


class DcmuHttp:
    """Read-only client for the DCMU web API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
        event_window: int = 20,
    ) -> None:
        self._session = session
        self._base = f"http://{host}/Data.php"
        token = base64.b64encode(f"{username}:{password}".encode("latin-1")).decode()
        self._headers = {"Authorization": f"Basic {token}"}
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self.event_window = event_window
        self.events = EventTracker()

    async def _get(self, params: dict[str, str]) -> str:
        try:
            async with self._session.get(
                self._base, params=params, headers=self._headers, timeout=self._timeout
            ) as resp:
                if resp.status == 401:
                    raise DcmuHttpAuthError("Web login rejected")
                if resp.status != 200:
                    raise DcmuHttpError(f"HTTP {resp.status}")
                return (await resp.read()).decode("latin-1")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DcmuHttpError(str(err) or type(err).__name__) from err

    async def read(self, area: str, address: int, length: int) -> list[int]:
        """Read raw bytes from RAM ('R') or flash ('F')."""
        return parse_array(await self._get({"code": read_code(area, address, length)}), length)

    async def read_versions(self) -> tuple[str, str]:
        """Firmware and hardware version, e.g. ('3.00', '2.02'). Also validates the login."""
        b = await self.read("F", *_FLASH_VERSIONS)
        return f"{b[0]}.{b[1]:02d}", f"{b[4]}.{b[5]:02d}"

    async def read_events(self) -> list[DeviceEvent]:
        """Newest event log rows."""
        return parse_events(await self._get({"log": "3", "len": str(self.event_window)}))

    async def read_state(self, state: HttpState | None = None) -> HttpState:
        """Read everything the integration uses from HTTP (3 requests)."""
        state = state or HttpState()
        if state.sw_version is None:
            state.sw_version, state.hw_version = await self.read_versions()

        ram_start, ram_len = _RAM_BLOCK
        ram = await self.read("R", ram_start, ram_len)

        def r(addr: int) -> int:
            return ram[addr - ram_start]

        state.apparent_energy = [_u32(ram, 32 + 4 * i - ram_start) for i in range(NUM_OUTLETS)]
        state.external_temperatures = [_temp(r(112 + i)) for i in range(NUM_OUTLETS)]
        state.airflow = None if r(122) == 255 else r(122) / 10
        state.intrusion = (bool(r(123) & 0x80), bool(r(123) & 0x40))
        clock = _u32(ram, 124 - ram_start)
        state.device_time = datetime.fromtimestamp(clock, UTC) if clock else None

        flash = await self.read("F", *_FLASH_LIFETIME)
        state.lifetime_energy = [_u32(flash, 4 * i) for i in range(NUM_OUTLETS)]

        state.new_events = self.events.new(await self.read_events())
        return state
