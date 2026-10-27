import pytest

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.protocol import MOTOR_CHAR, MOVE_PERCENT_CHAR, NOTIFY_CHAR, POSITION_CHAR, MotorCommand
from soma_shades.exceptions import InvalidValueError, ShadeConnectionError, ShadeNotConnectedError
from tests.conftest import FakeBluetooth


def test_to_dict_and_from_dict() -> None:
    shade = ShadeClient(mac="AA:BB", name="Living Room", manufacturer="Wazombi Labs", serial_number="123")
    data = shade.to_dict()
    assert data["name"] == "living_room"
    restored = ShadeClient.from_dict({**data, "unknown": "ignored"})
    assert restored.to_dict() == data


def test_display_name() -> None:
    assert ShadeClient(mac="AA:BB", name="kitchen_window").display_name == "Kitchen Window"


@pytest.mark.parametrize(
    ("position", "target", "status"),
    [
        (None, None, None),
        (0, 0, "open"),
        (100, 100, "closed"),
        (50, 20, "opening"),
        (50, 80, "closing"),
        (50, 50, "stopped"),
    ],
)
def test_cover_status(position: int | None, target: int | None, status: str | None) -> None:
    shade = ShadeClient(mac="AA:BB", name="shade")
    shade._position, shade._target_position = position, target
    assert shade.cover_status == status


@pytest.mark.parametrize("target", ["abc", 101, -1])
async def test_set_position_rejects_invalid_values(shade: ShadeClient, target: int | str) -> None:
    with pytest.raises(InvalidValueError):
        await shade.set_position(target)


async def test_commands_require_a_connection(shade: ShadeClient) -> None:
    with pytest.raises(ShadeNotConnectedError):
        await shade.get_position()


async def test_connect_and_disconnect(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    await shade.connect(timeout=1)
    assert shade.is_connected() and shade.connected

    await shade.connect(timeout=1)  # already connected
    assert len(bluetooth.clients) == 1

    await shade.disconnect()
    assert not shade.is_connected() and not shade.connected
    await shade.wait_until_disconnected()


async def test_connection_dropped_by_the_shade(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    await shade.connect(timeout=1)
    bluetooth.client.drop()
    assert not shade.connected
    await shade.wait_until_disconnected()

    await shade.connect(timeout=1)
    assert len(bluetooth.clients) == 2


async def test_connection_failure(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    bluetooth.fail = True
    with pytest.raises(ShadeConnectionError):
        await shade.connect(timeout=1)
    assert shade.ble_device is None  # rescan on the next attempt


async def test_move_and_set_position(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    updates: list[str | None] = []
    shade.on_update = lambda: updates.append(shade.cover_status)
    bluetooth.values[POSITION_CHAR] = bytes([100])
    await shade.connect(timeout=1)
    await shade.get_position()

    await shade.move_up()
    await shade.set_position("40")

    assert bluetooth.client.writes == [(MOTOR_CHAR, bytes([MotorCommand.UP])), (MOVE_PERCENT_CHAR, bytes([40]))]
    assert updates == ["closed", "opening", "opening"]


async def test_position_notification(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    updates: list[int | None] = []
    shade.on_update = lambda: updates.append(shade.position)
    bluetooth.values[MOVE_PERCENT_CHAR] = bytes([30])
    await shade.connect(timeout=1)
    await shade.start_notify("position")

    await bluetooth.client.notify_handlers[POSITION_CHAR](None, bytearray([30]))

    assert shade.position == 30
    assert shade.cover_status == "stopped"
    assert updates == [30]


async def test_identify_plays_a_sound(shade: ShadeClient, bluetooth: FakeBluetooth) -> None:
    await shade.connect(timeout=1)
    await shade.identify()
    await shade.identify(0x10)
    assert bluetooth.client.writes == [(NOTIFY_CHAR, b"\x01"), (NOTIFY_CHAR, b"\x10")]
