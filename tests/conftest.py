import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakNotFoundError

import soma_shades.ble.client as client_module
from soma_shades.ble.client import ShadeClient
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.ble.protocol import (
    BATTERY_LEVEL_CHAR,
    BATTERY_VOLTAGE_CHAR,
    CHARGING_CHAR,
    MOVE_PERCENT_CHAR,
    POSITION_CHAR,
)
from soma_shades.mqtt.bridge import MQTTBridge
from soma_shades.mqtt.config import BridgeConfig


class FakeBleakClient:
    """A connected BleakClient of a shade."""

    def __init__(
        self, disconnected_callback: Callable[[Any], None], values: dict[uuid.UUID, bytes], missing: set[uuid.UUID]
    ):
        self.disconnected_callback = disconnected_callback
        self.values = values
        self.missing = missing
        self.is_connected = True
        self.services: list[Any] = []
        self.reads: list[uuid.UUID] = []
        self.writes: list[tuple[uuid.UUID, bytes]] = []
        self.notify_handlers: dict[uuid.UUID, Callable[..., Any]] = {}

    async def read_gatt_char(self, char: uuid.UUID) -> bytearray:
        self.reads.append(char)
        if char in self.missing:
            raise BleakError(f"Characteristic {char} was not found")
        return bytearray(self.values.get(char, b"\x00"))

    async def write_gatt_char(self, char: uuid.UUID, data: bytes, response: bool = True) -> None:
        self.writes.append((char, bytes(data)))

    async def start_notify(self, char: uuid.UUID, handler: Callable[..., Any]) -> None:
        self.notify_handlers[char] = handler

    async def stop_notify(self, char: uuid.UUID) -> None:
        self.notify_handlers.pop(char, None)

    async def disconnect(self) -> None:
        if self.is_connected:
            self.is_connected = False
            self.disconnected_callback(self)

    def drop(self) -> None:
        """Simulate a connection dropped by the shade."""
        self.is_connected = False
        self.disconnected_callback(self)


class FakeBluetooth:
    """Replaces the Bluetooth stack: scanning and establishing connections."""

    def __init__(self) -> None:
        self.clients: list[FakeBleakClient] = []
        self.fail = False  # connection attempts fail
        self.hang = False  # connection attempts never finish
        self.values = {
            POSITION_CHAR: b"\x64",
            MOVE_PERCENT_CHAR: b"\x64",
            BATTERY_LEVEL_CHAR: b"\x5a",  # 90%
            BATTERY_VOLTAGE_CHAR: (395).to_bytes(2, "little"),  # 3950 mV
            CHARGING_CHAR: (605).to_bytes(2, "little") + (615).to_bytes(2, "little"),  # charging
        }
        self.missing: set[uuid.UUID] = set()  # characteristics the firmware does not have

    @property
    def client(self) -> FakeBleakClient:
        return self.clients[-1]

    async def establish_connection(
        self, client_class: type, device: BLEDevice, name: str, disconnected_callback: Callable[[Any], None], **_: Any
    ) -> FakeBleakClient:
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail:
            raise BleakNotFoundError(f"{name} not found")
        client = FakeBleakClient(disconnected_callback, self.values, self.missing)
        self.clients.append(client)
        return client


class FakeMQTTClient:
    """Records the published messages."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Any, bool]] = []

    async def publish(self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload, retain))

    def payloads(self, topic: str) -> list[Any]:
        return [payload for published_topic, payload, _ in self.published if published_topic == topic]


async def wait_until(condition: Callable[[], bool], timeout: float = 2) -> None:
    async with asyncio.timeout(timeout):
        while not condition():  # noqa: ASYNC110 - polling the state of the fakes
            await asyncio.sleep(0.01)


@pytest.fixture
def bluetooth(monkeypatch: pytest.MonkeyPatch) -> FakeBluetooth:
    fake = FakeBluetooth()

    async def scan(self: ShadeClient, timeout: float) -> BLEDevice:
        return BLEDevice(self.mac, "S", None)

    monkeypatch.setattr(client_module, "establish_connection", fake.establish_connection)
    monkeypatch.setattr(ShadeClient, "scan", scan)
    return fake


@pytest.fixture
def shade(bluetooth: FakeBluetooth) -> ShadeClient:
    # with a manufacturer the bridge skips reading the info and the beep on the first connection
    return ShadeClient(mac="AA:BB:CC:DD:EE:FF", name="Living Room", manufacturer="Wazombi Labs")


@pytest.fixture
def fleet(tmp_path: Path, shade: ShadeClient) -> ShadeFleet:
    fleet = ShadeFleet(tmp_path / "shades.json")
    fleet.add(shade)
    return fleet


@pytest.fixture
async def bridge(fleet: ShadeFleet) -> AsyncIterator[MQTTBridge]:
    config = BridgeConfig(
        reconnect_backoff_min=0.05,
        stable_connection_time=0,
        keepalive_interval=0.1,
        offline_grace_period=0.3,
    )
    bridge = MQTTBridge(fleet, config)
    bridge.client = cast(Any, FakeMQTTClient())
    yield bridge
    await bridge.shutdown()


def mqtt_client(bridge: MQTTBridge) -> FakeMQTTClient:
    return cast(FakeMQTTClient, bridge.client)
