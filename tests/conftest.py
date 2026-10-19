"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from custom_components.racktivity_dcmu.snmp import (
    NoSuchObject,
    SnmpErrorStatus,
    SnmpTimeout,
    SnmpValue,
)

from .synthetic import snmp_values

HOST = "192.0.2.10"
READ_COMMUNITY = "public"
WRITE_COMMUNITY = "private"


def load_values() -> dict[str, SnmpValue]:
    """Synthetic SNMP values (see synthetic.py; nothing recorded from a device)."""
    return snmp_values()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


class FakeSnmpClient:
    """In-memory stand-in for SnmpClient, mimicking the DCMU agent."""

    instances: ClassVar[list[FakeSnmpClient]] = []
    values: ClassVar[dict[str, SnmpValue]] = {}
    offline = False
    write_community = WRITE_COMMUNITY

    def __init__(self, host: str, port: int = 161, community: str = "public", **_: Any) -> None:
        self.host = host
        self.port = port
        self.community = community
        self.sets: list[tuple[str, SnmpValue]] = []
        self.gets = 0
        self.closed = False
        FakeSnmpClient.instances.append(self)

    async def get(self, oids: Iterable[str]) -> dict[str, SnmpValue]:
        self.gets += 1
        if self.offline or self.community != READ_COMMUNITY:
            raise SnmpTimeout("offline")
        return {o: self.values.get(o, NoSuchObject(0x80)) for o in oids}

    async def set(self, varbinds, community: str) -> dict[str, SnmpValue]:
        if self.offline or community != self.write_community:
            raise SnmpTimeout("wrong community")
        for oid, val in varbinds:
            if oid not in self.values:
                raise SnmpErrorStatus(17, 1, oid)
            self.sets.append((oid, val))
            self.values[oid] = val
        return dict(varbinds)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_snmp() -> Generator[type[FakeSnmpClient]]:
    """Patch SnmpClient everywhere the integration constructs it."""
    FakeSnmpClient.instances = []
    FakeSnmpClient.values = load_values()
    FakeSnmpClient.offline = False
    with (
        patch("custom_components.racktivity_dcmu.SnmpClient", FakeSnmpClient),
        patch("custom_components.racktivity_dcmu.config_flow.SnmpClient", FakeSnmpClient),
    ):
        yield FakeSnmpClient
