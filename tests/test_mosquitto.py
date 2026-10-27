"""End-to-end tests of the bridge with a real Mosquitto broker, skipped when mosquitto is not installed."""

import asyncio
import json
import shutil
import socket
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aiomqtt
import pytest

from soma_shades.ble.fleet import ShadeFleet
from soma_shades.mqtt.bridge import MQTTBridge
from soma_shades.mqtt.config import BridgeConfig
from soma_shades.mqtt.topics import BRIDGE_AVAILABILITY_TOPIC, SMARTSHADE_TOPIC, shade_topic
from tests.conftest import FakeBluetooth

MOSQUITTO = shutil.which("mosquitto") or next(
    (path for path in ("/usr/sbin/mosquitto", "/opt/homebrew/sbin/mosquitto") if Path(path).exists()), None
)
pytestmark = [
    pytest.mark.mosquitto,
    pytest.mark.skipif(MOSQUITTO is None, reason="mosquitto is not installed"),
]


@pytest.fixture
def broker_port() -> Iterator[int]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    assert MOSQUITTO
    process = subprocess.Popen([MOSQUITTO, "-p", str(port)], stderr=subprocess.DEVNULL)
    yield port
    process.terminate()
    process.wait()


@pytest.fixture
async def running_bridge(fleet: ShadeFleet, bluetooth: FakeBluetooth, broker_port: int) -> AsyncIterator[MQTTBridge]:
    await asyncio.sleep(0.3)  # wait for the broker to start
    bridge = MQTTBridge(fleet, BridgeConfig(broker="127.0.0.1", port=broker_port, status_table_interval=0))
    task = asyncio.create_task(bridge.run(discover=False))
    yield bridge
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def retained_messages(port: int) -> dict[str, str]:
    """Subscribe like Home Assistant does after processing a discovery message: only retained messages arrive."""
    messages: dict[str, str] = {}
    async with aiomqtt.Client("127.0.0.1", port) as client:
        await client.subscribe(f"{SMARTSHADE_TOPIC}/#")
        try:
            async with asyncio.timeout(0.5):
                async for message in client.messages:
                    assert isinstance(message.payload, bytes)
                    messages[message.topic.value] = message.payload.decode()
        except TimeoutError:
            pass
    return messages


async def test_home_assistant_gets_the_retained_covers(running_bridge: MQTTBridge, broker_port: int) -> None:
    await asyncio.sleep(0.5)
    messages = await retained_messages(broker_port)

    assert messages[BRIDGE_AVAILABILITY_TOPIC] == "online"
    assert messages[shade_topic("living_room", "availability")] == "online"
    assert messages[shade_topic("living_room", "state")] == "closed"
    assert json.loads(messages[shade_topic("living_room", "config")])["unique_id"] == "living_room"


async def test_command_through_the_broker(
    running_bridge: MQTTBridge, bluetooth: FakeBluetooth, broker_port: int
) -> None:
    await asyncio.sleep(0.5)
    async with aiomqtt.Client("127.0.0.1", broker_port) as client:
        await client.publish(shade_topic("living_room", "set_position"), "25")
    await asyncio.sleep(0.3)

    assert bluetooth.client.writes[-1][1] == bytes([25])


async def test_bridge_offline_after_stop(fleet: ShadeFleet, bluetooth: FakeBluetooth, broker_port: int) -> None:
    await asyncio.sleep(0.3)
    bridge = MQTTBridge(fleet, BridgeConfig(broker="127.0.0.1", port=broker_port, status_table_interval=0))
    task = asyncio.create_task(bridge.run(discover=False))
    await asyncio.sleep(0.5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    messages = await retained_messages(broker_port)
    assert messages[BRIDGE_AVAILABILITY_TOPIC] == "offline"
    assert messages[shade_topic("living_room", "availability")] == "offline"
