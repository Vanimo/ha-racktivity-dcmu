"""Minimal asyncio SNMP v1/v2c client (GET and SET).

Self-contained on purpose: the integration only needs a handful of GETs and
the occasional SET, and avoiding pysnmp keeps it clear of Home Assistant's
pinned pysnmp version.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# BER universal tags
_INTEGER = 0x02
_OCTET_STRING = 0x04
_NULL = 0x05
_OID = 0x06
_SEQUENCE = 0x30
# SNMP application tags
_IP_ADDRESS = 0x40
_COUNTER32 = 0x41
_GAUGE32 = 0x42
_TIMETICKS = 0x43
_OPAQUE = 0x44
_COUNTER64 = 0x46
# SNMPv2 varbind exceptions
_NO_SUCH_OBJECT = 0x80
_NO_SUCH_INSTANCE = 0x81
_END_OF_MIB_VIEW = 0x82
# PDU types
_GET_REQUEST = 0xA0
_GET_RESPONSE = 0xA2
_SET_REQUEST = 0xA3

VERSION_1 = 0
VERSION_2C = 1

ERROR_NAMES = {
    0: "noError",
    1: "tooBig",
    2: "noSuchName",
    3: "badValue",
    4: "readOnly",
    5: "genErr",
    6: "noAccess",
    7: "wrongType",
    8: "wrongLength",
    9: "wrongEncoding",
    10: "wrongValue",
    11: "noCreation",
    12: "inconsistentValue",
    13: "resourceUnavailable",
    14: "commitFailed",
    15: "undoFailed",
    16: "authorizationError",
    17: "notWritable",
    18: "inconsistentName",
}


class SnmpError(Exception):
    """Base error for SNMP failures."""


class SnmpTimeout(SnmpError):
    """No response from the agent."""


class SnmpErrorStatus(SnmpError):
    """The agent answered with a non-zero error-status."""

    def __init__(self, status: int, index: int, oid: str | None) -> None:
        self.status = status
        self.index = index
        self.oid = oid
        super().__init__(f"{ERROR_NAMES.get(status, status)} (index {index}, oid {oid})")


class NoSuchObject:
    """Marker for noSuchObject / noSuchInstance / endOfMibView varbinds."""

    __slots__ = ("tag",)

    def __init__(self, tag: int) -> None:
        self.tag = tag

    def __repr__(self) -> str:
        return f"NoSuchObject(0x{self.tag:02x})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NoSuchObject) and other.tag == self.tag

    def __hash__(self) -> int:
        return hash(self.tag)


SnmpValue = int | bytes | str | None | NoSuchObject


# --------------------------------------------------------------------------- BER


def _enc_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(out)]) + out


def _tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _enc_len(len(payload)) + payload


def _enc_int(value: int, tag: int = _INTEGER) -> bytes:
    length = max(1, (value.bit_length() + 8) // 8)
    return _tlv(tag, value.to_bytes(length, "big", signed=True))


def _enc_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip(".").split(".")]
    if len(parts) < 2:
        raise ValueError(f"OID too short: {oid}")
    body = bytearray([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        body.extend(reversed(chunk))
    return _tlv(_OID, bytes(body))


def _enc_value(value: SnmpValue) -> bytes:
    if value is None:
        return _tlv(_NULL, b"")
    if isinstance(value, NoSuchObject):
        return _tlv(value.tag, b"")
    if isinstance(value, bool):
        raise TypeError("bool is not a valid SNMP value")
    if isinstance(value, int):
        return _enc_int(value)
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return _tlv(_OCTET_STRING, value)
    raise TypeError(f"Unsupported SNMP value type: {type(value)!r}")


def _dec_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """Decode one TLV at pos, return (tag, payload, next_pos)."""
    if pos + 2 > len(data):
        raise SnmpError("Truncated BER data")
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        nbytes = length & 0x7F
        if nbytes == 0 or pos + nbytes > len(data):
            raise SnmpError("Bad BER length")
        length = int.from_bytes(data[pos : pos + nbytes], "big")
        pos += nbytes
    end = pos + length
    if end > len(data):
        raise SnmpError("Truncated BER payload")
    return tag, data[pos:end], end


def _dec_oid(payload: bytes) -> str:
    if not payload:
        raise SnmpError("Empty OID")
    first = payload[0]
    parts = [first // 40, first % 40] if first < 80 else [2, first - 80]
    value = 0
    for byte in payload[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(str(p) for p in parts)


def _dec_value(tag: int, payload: bytes) -> SnmpValue:
    if tag == _INTEGER:
        return int.from_bytes(payload, "big", signed=True) if payload else 0
    if tag in (_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64):
        return int.from_bytes(payload, "big", signed=False) if payload else 0
    if tag == _OCTET_STRING or tag == _OPAQUE:
        return payload
    if tag == _IP_ADDRESS:
        return ".".join(str(b) for b in payload)
    if tag == _OID:
        return _dec_oid(payload)
    if tag == _NULL:
        return None
    if tag in (_NO_SUCH_OBJECT, _NO_SUCH_INSTANCE, _END_OF_MIB_VIEW):
        return NoSuchObject(tag)
    return payload


def encode_request(
    pdu_type: int,
    version: int,
    community: str,
    request_id: int,
    varbinds: Sequence[tuple[str, SnmpValue]],
    error_status: int = 0,
    error_index: int = 0,
) -> bytes:
    """Encode an SNMP v1/v2c message (requests; responses for test agents)."""
    vbs = b"".join(_tlv(_SEQUENCE, _enc_oid(oid) + _enc_value(val)) for oid, val in varbinds)
    pdu = _tlv(
        pdu_type,
        _enc_int(request_id)
        + _enc_int(error_status)
        + _enc_int(error_index)
        + _tlv(_SEQUENCE, vbs),
    )
    return _tlv(_SEQUENCE, _enc_int(version) + _enc_value(community) + pdu)


@dataclass(slots=True)
class Response:
    """Decoded SNMP response."""

    version: int
    community: bytes
    pdu_type: int
    request_id: int
    error_status: int
    error_index: int
    varbinds: list[tuple[str, SnmpValue]]


def decode_message(data: bytes) -> Response:
    """Decode an SNMP v1/v2c message (any PDU type with the standard layout)."""
    tag, msg, _ = _dec_tlv(data, 0)
    if tag != _SEQUENCE:
        raise SnmpError("Message is not a SEQUENCE")
    tag, ver, pos = _dec_tlv(msg, 0)
    tag, community, pos = _dec_tlv(msg, pos)
    pdu_type, pdu, _ = _dec_tlv(msg, pos)
    _, rid, p = _dec_tlv(pdu, 0)
    _, est, p = _dec_tlv(pdu, p)
    _, eidx, p = _dec_tlv(pdu, p)
    _, vbl, _ = _dec_tlv(pdu, p)
    varbinds: list[tuple[str, SnmpValue]] = []
    p = 0
    while p < len(vbl):
        _, vb, p = _dec_tlv(vbl, p)
        _, oid_payload, q = _dec_tlv(vb, 0)
        vtag, vpayload, _ = _dec_tlv(vb, q)
        varbinds.append((_dec_oid(oid_payload), _dec_value(vtag, vpayload)))
    return Response(
        version=int.from_bytes(ver, "big"),
        community=community,
        pdu_type=pdu_type,
        request_id=int.from_bytes(rid, "big", signed=True),
        error_status=int.from_bytes(est, "big"),
        error_index=int.from_bytes(eidx, "big"),
        varbinds=varbinds,
    )


# ------------------------------------------------------------------------ client


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.pending: dict[int, asyncio.Future[Response]] = {}
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            resp = decode_message(data)
        except (SnmpError, IndexError, ValueError):
            return
        fut = self.pending.get(resp.request_id)
        if fut is not None and not fut.done():
            fut.set_result(resp)

    def error_received(self, exc: Exception) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(SnmpError(str(exc)))

    def connection_lost(self, exc: Exception | None) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(SnmpError("Transport closed"))


class SnmpClient:
    """Async SNMP client bound to one agent.

    Requests are serialised: the DCMU agent is a small embedded device and
    handles one request at a time best.
    """

    def __init__(
        self,
        host: str,
        port: int = 161,
        community: str = "public",
        *,
        version: int = VERSION_2C,
        timeout: float = 2.0,
        retries: int = 2,
        max_oids_per_request: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.community = community
        self.version = version
        self.timeout = timeout
        self.retries = retries
        self.max_oids_per_request = max_oids_per_request
        self._protocol: _Protocol | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._lock = asyncio.Lock()
        self._request_id = random.randint(1, 0x3FFFFFFF)

    async def _ensure_transport(self) -> _Protocol:
        if self._transport is None or self._transport.is_closing():
            loop = asyncio.get_running_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                _Protocol, remote_addr=(self.host, self.port)
            )
            self._transport = transport
            self._protocol = protocol
        assert self._protocol is not None
        return self._protocol

    def close(self) -> None:
        """Close the UDP socket."""
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._protocol = None

    def _next_id(self) -> int:
        self._request_id = (self._request_id % 0x7FFFFFFF) + 1
        return self._request_id

    async def _request(
        self,
        pdu_type: int,
        varbinds: Sequence[tuple[str, SnmpValue]],
        community: str,
    ) -> Response:
        async with self._lock:
            protocol = await self._ensure_transport()
            loop = asyncio.get_running_loop()
            for _attempt in range(self.retries + 1):
                rid = self._next_id()
                fut: asyncio.Future[Response] = loop.create_future()
                protocol.pending[rid] = fut
                try:
                    assert protocol.transport is not None
                    protocol.transport.sendto(
                        encode_request(pdu_type, self.version, community, rid, varbinds)
                    )
                    async with asyncio.timeout(self.timeout):
                        return await fut
                except TimeoutError:
                    continue
                finally:
                    protocol.pending.pop(rid, None)
            raise SnmpTimeout(f"No SNMP response from {self.host}:{self.port}")

    async def get(self, oids: Iterable[str]) -> dict[str, SnmpValue]:
        """GET a list of OIDs, chunked to stay under the agent's size limit.

        Missing OIDs map to a NoSuchObject marker instead of raising.
        """
        oid_list = list(oids)
        result: dict[str, SnmpValue] = {}
        for start in range(0, len(oid_list), self.max_oids_per_request):
            chunk = oid_list[start : start + self.max_oids_per_request]
            result.update(await self._get_chunk(chunk))
        return result

    async def _get_chunk(self, oids: list[str]) -> dict[str, SnmpValue]:
        resp = await self._request(_GET_REQUEST, [(o, None) for o in oids], self.community)
        if resp.error_status == 0:
            if len(resp.varbinds) == len(oids):
                # Map by position: the DCMU agent mangles the echoed OID of
                # missing objects (appends ".0").
                return {oid: val for oid, (_, val) in zip(oids, resp.varbinds, strict=True)}
            return dict(resp.varbinds)
        if (
            resp.error_status == 2
            and self.version == VERSION_1
            and 0 < resp.error_index <= len(oids)
        ):
            # SNMPv1: drop the failing OID and retry the rest.
            bad = oids[resp.error_index - 1]
            rest = [o for o in oids if o != bad]
            out = await self._get_chunk(rest) if rest else {}
            out[bad] = NoSuchObject(_NO_SUCH_OBJECT)
            return out
        if resp.error_status == 1 and len(oids) > 1:
            # tooBig: split and retry.
            half = len(oids) // 2
            out = await self._get_chunk(oids[:half])
            out.update(await self._get_chunk(oids[half:]))
            return out
        idx = resp.error_index
        raise SnmpErrorStatus(
            resp.error_status, idx, oids[idx - 1] if 0 < idx <= len(oids) else None
        )

    async def set(
        self, varbinds: Sequence[tuple[str, int | bytes | str]], community: str
    ) -> dict[str, SnmpValue]:
        """SET one or more values using the given (write) community."""
        resp = await self._request(_SET_REQUEST, list(varbinds), community)
        if resp.error_status:
            idx = resp.error_index
            oid = varbinds[idx - 1][0] if 0 < idx <= len(varbinds) else None
            raise SnmpErrorStatus(resp.error_status, idx, oid)
        return dict(resp.varbinds)
