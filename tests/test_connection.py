import asyncio
from collections.abc import AsyncIterator

import pytest
from bleak.backends.device import BLEDevice

from soma_shades import ConnectionConfig, ShadeClient, ShadeConnection, ShadeConnectionError, ShadeDisabledError
from soma_shades.ble.protocol import POSITION_CHAR, TIME_CHAR

from .conftest import FakeBluetooth, wait_until

CONFIG = ConnectionConfig(reconnect_backoff_min=0.05, stable_connection_time=0, keepalive_interval=0.05)


@pytest.fixture
async def connection(shade: ShadeClient) -> AsyncIterator[ShadeConnection]:
    connection = ShadeConnection(shade, CONFIG)
    yield connection
    await connection.stop()


async def test_reports_the_availability(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    reported: list[bool] = []

    async def on_availability(online: bool) -> None:
        reported.append(online)

    connection = ShadeConnection(shade, CONFIG, on_availability=on_availability)
    connection.start()
    await wait_until(lambda: connection.online)

    await connection.stop()
    assert reported == [True, False]
    assert not shade.is_connected()


async def test_connects_to_the_device_of_find_device(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    device = BLEDevice(shade.mac, "S", None)
    connection = ShadeConnection(shade, CONFIG, find_device=lambda mac: device)
    connection.start()
    await wait_until(lambda: connection.online)

    assert shade.ble_device is device
    await connection.stop()


async def test_command_fails_when_no_adapter_sees_the_shade(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    connection = ShadeConnection(shade, CONFIG, find_device=lambda mac: None)

    with pytest.raises(ShadeConnectionError):
        await connection.run_command(shade.move_up)


async def test_disabled_shade_refuses_commands(
    shade: ShadeClient, bluetooth: FakeBluetooth, connection: ShadeConnection
) -> None:
    shade.bluetooth_enabled = False

    connection.start()
    await asyncio.sleep(0.02)
    assert not bluetooth.clients
    with pytest.raises(ShadeDisabledError):
        await connection.run_command(shade.move_up)


async def test_first_connection_reads_the_info(bluetooth: FakeBluetooth) -> None:
    shade = ShadeClient(mac="AA:BB:CC:DD:EE:FF", name="Living Room")
    calls: list[int] = []

    async def on_first_connection() -> None:
        calls.append(1)

    connection = ShadeConnection(shade, CONFIG, on_first_connection=on_first_connection)
    connection.start()
    await wait_until(lambda: connection.online)

    assert calls == [1]
    await connection.stop()


async def test_refreshes_the_position(
    shade: ShadeClient, bluetooth: FakeBluetooth, connection: ShadeConnection
) -> None:
    connection.config = ConnectionConfig(keepalive_interval=0.02, update_interval=0)
    connection.start()
    await wait_until(lambda: connection.online)

    bluetooth.values[POSITION_CHAR] = bytes([25])
    await wait_until(lambda: shade.position == 25)


def test_ble_device_as_argument() -> None:
    device = BLEDevice("AA:BB", "S", None)
    assert ShadeClient(mac="AA:BB", name="Living Room", ble_device=device).ble_device is device


async def test_hanging_connection_does_not_block_the_other_shades(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    config = ConnectionConfig(reconnect_backoff_min=0.05, stable_connection_time=0, setup_timeout=0.1)
    semaphore = asyncio.Semaphore(1)
    other = ShadeClient(mac="11:22:33:44:55:66", name="Kitchen", manufacturer="Wazombi Labs")
    bluetooth.hanging.add(POSITION_CHAR)
    hanging = ShadeConnection(shade, config, connect_semaphore=semaphore)
    hanging.start()
    await wait_until(lambda: len(bluetooth.clients) == 1)

    bluetooth.hanging.clear()
    connection = ShadeConnection(other, config, connect_semaphore=semaphore)
    connection.start()
    await wait_until(lambda: connection.online and hanging.online)

    await connection.stop()
    await hanging.stop()


async def test_hanging_keepalive_reconnects(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    config = ConnectionConfig(
        reconnect_backoff_min=0.05, stable_connection_time=0, keepalive_interval=0.05, operation_timeout=0.1
    )
    connection = ShadeConnection(shade, config)
    connection.start()
    await wait_until(lambda: connection.online)

    bluetooth.hanging.add(TIME_CHAR)
    await wait_until(lambda: len(bluetooth.clients) == 2)
    bluetooth.hanging.clear()
    await wait_until(lambda: shade.is_connected())
    await connection.stop()


async def test_hanging_command_fails(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    connection = ShadeConnection(shade, ConnectionConfig(operation_timeout=0.1))

    async def hang() -> None:
        await asyncio.sleep(3600)

    with pytest.raises(ShadeConnectionError, match="timed out"):
        await connection.run_command(hang)
    assert not shade.is_connected()
    await connection.stop()
