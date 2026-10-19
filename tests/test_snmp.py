"""Tests for the minimal SNMP client, against a local UDP fake agent."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest

from custom_components.racktivity_dcmu import snmp
from custom_components.racktivity_dcmu.snmp import (
    NoSuchObject,
    SnmpClient,
    SnmpErrorStatus,
    SnmpTimeout,
    decode_message,
    encode_request,
)

from .conftest import load_values


def test_roundtrip_request() -> None:
    """Encoded requests decode back to the same fields."""
    vbs = [
        ("1.3.6.1.4.1.34097.3.1.1.7.0", 1),
        ("1.3.6.1.2.1.1.1.0", None),
        ("1.3.6.1.4.1.34097.2.18.0", -76),
        ("1.3.6.1.4.1.34097.2.10.0", 1700000000),
        ("1.3.6.1.4.1.34097.2.15.0", b"Test PDU"),
        ("1.3.6.1.4.1.999999.2147483647.0", 0),
    ]
    msg = decode_message(encode_request(0xA3, 1, "private", 1234, vbs))
    assert msg.version == 1
    assert msg.community == b"private"
    assert msg.pdu_type == 0xA3
    assert msg.request_id == 1234
    assert msg.varbinds == vbs


def test_known_encoding() -> None:
    """Byte-exact BER for a v2c GET of sysDescr.0 (request-id 1)."""
    expected = bytes.fromhex(
        "302602010104067075626c6963a019020101020100020100300e300c06082b060102010101000500"
    )
    assert encode_request(0xA0, 1, "public", 1, [("1.3.6.1.2.1.1.1.0", None)]) == expected


def test_decode_exceptions_and_app_types() -> None:
    """noSuchObject, Counter32, IpAddress and TimeTicks decode."""
    # Build varbinds by hand: tag/len/payload after OID.
    oid = snmp._enc_oid("1.3.6.1.2.1.1.3.0")
    vbs = (
        snmp._tlv(0x30, oid + bytes([0x43, 0x04]) + (123456789).to_bytes(4, "big"))
        + snmp._tlv(0x30, oid + bytes([0x40, 0x04, 192, 0, 2, 10]))
        + snmp._tlv(0x30, oid + bytes([0x81, 0x00]))
    )
    pdu = snmp._tlv(
        0xA2, snmp._enc_int(7) + snmp._enc_int(0) + snmp._enc_int(0) + snmp._tlv(0x30, vbs)
    )
    data = snmp._tlv(0x30, snmp._enc_int(1) + snmp._enc_value("public") + pdu)
    values = [v for _, v in decode_message(data).varbinds]
    assert values == [123456789, "192.0.2.10", NoSuchObject(0x81)]


class FakeAgent(asyncio.DatagramProtocol):
    """UDP agent with the DCMU's quirks.

    - a request containing an unknown OID gets no answer at all;
    - more than max_oids varbinds gets no answer (size limit);
    - SET needs the write community.
    """

    def __init__(self, values: dict, max_oids: int = 56) -> None:
        self.values = values
        self.max_oids = max_oids
        self.requests = 0
        self.drop_next = 0
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        self.requests += 1
        if self.drop_next:
            self.drop_next -= 1
            return
        msg = decode_message(data)
        if msg.community not in (b"public", b"private"):
            return
        oids = [o for o, _ in msg.varbinds]
        if len(oids) > self.max_oids or any(o not in self.values for o in oids):
            return
        if msg.pdu_type == 0xA3:
            if msg.community != b"private":
                reply = encode_request(
                    0xA2, msg.version, "private", msg.request_id, msg.varbinds, 16, 1
                )
            else:
                for o, v in msg.varbinds:
                    self.values[o] = v
                reply = encode_request(0xA2, msg.version, "private", msg.request_id, msg.varbinds)
        else:
            reply = encode_request(
                0xA2, msg.version, "public", msg.request_id, [(o, self.values[o]) for o in oids]
            )
        assert self.transport is not None
        self.transport.sendto(reply, addr)


@pytest.fixture
async def agent(socket_enabled) -> AsyncGenerator[tuple[FakeAgent, int]]:
    """Run a fake agent on localhost."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: FakeAgent(load_values()), local_addr=("127.0.0.1", 0)
    )
    yield protocol, transport.get_extra_info("sockname")[1]
    transport.close()


async def test_get_chunks(agent) -> None:
    """Large GETs are split into chunks the agent accepts."""
    proto, port = agent
    client = SnmpClient("127.0.0.1", port, max_oids_per_request=30, timeout=0.5, retries=0)
    oids = [o for o in proto.values if o.startswith("1.3.6.1.4.1.34097")]
    assert len(oids) > 100
    result = await client.get(oids)
    client.close()
    assert result == {o: proto.values[o] for o in oids}
    assert proto.requests == -(-len(oids) // 30)


async def test_retry_after_drop(agent) -> None:
    """A dropped datagram is retried."""
    proto, port = agent
    proto.drop_next = 1
    client = SnmpClient("127.0.0.1", port, timeout=0.2, retries=1)
    result = await client.get(["1.3.6.1.4.1.34097.1.1.0"])
    client.close()
    assert result == {"1.3.6.1.4.1.34097.1.1.0": b"DCMU_8port"}
    assert proto.requests == 2


async def test_timeout(agent) -> None:
    """Unknown OIDs make the DCMU silent; that surfaces as a timeout."""
    _, port = agent
    client = SnmpClient("127.0.0.1", port, timeout=0.1, retries=1)
    with pytest.raises(SnmpTimeout):
        await client.get(["1.3.6.1.4.1.34097.9.9.0"])
    client.close()


async def test_set(agent) -> None:
    """SET uses the given community and reports agent errors."""
    proto, port = agent
    oid = "1.3.6.1.4.1.34097.3.1.1.7.5"
    client = SnmpClient("127.0.0.1", port, timeout=0.3, retries=0)
    await client.set([(oid, 1)], "private")
    assert proto.values[oid] == 1
    with pytest.raises(SnmpErrorStatus) as err:
        await client.set([(oid, 0)], "public")
    assert err.value.status == 16
    assert proto.values[oid] == 1
    client.close()
