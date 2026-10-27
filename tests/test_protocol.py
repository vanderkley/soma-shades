import pytest

from soma_shades.ble.protocol import (
    MANUFACTURER_ID,
    ConfigCommand,
    is_v3_shade,
    parse_config_notification,
    parse_device_name,
    parse_version,
)


def v2_manufacturer_data(name: str, version: int = 0x05) -> dict[int, bytes]:
    """Version, unknown byte, current and target position, the name followed by "0" and padded with spaces."""
    return {MANUFACTURER_ID: bytes([version, 0x00, 100, 100]) + f"{name}0".ljust(15).encode()}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Living Room", "living_room"),
        ("Room 10", "room_10"),  # only the "0" terminator is removed
        ("Kitchen", "kitchen"),
    ],
)
def test_parse_device_name(name: str, expected: str) -> None:
    assert parse_device_name(v2_manufacturer_data(name)) == expected


def test_parse_device_name_does_not_depend_on_the_version() -> None:
    assert parse_device_name(v2_manufacturer_data("Living Room", version=0x06)) == "living_room"


def test_parse_device_name_without_manufacturer_data() -> None:
    assert parse_device_name({}) == ""


def test_versions() -> None:
    v3_data = {MANUFACTURER_ID: bytes([0x10, 0x00, 0x32])}  # V3: version, position, battery level
    assert parse_version(v2_manufacturer_data("Kitchen")) == 0x05
    assert not is_v3_shade(v2_manufacturer_data("Kitchen"))
    assert is_v3_shade(v3_data)
    assert parse_version({}) is None
    assert not is_v3_shade({})


def test_parse_config_notification() -> None:
    data = bytes([0x00, 0x00, ConfigCommand.MOTOR_SPEED, 1, 50, ConfigCommand.MOTOR_CURRENT, 2, 0x10, 0x20])
    assert parse_config_notification(data) == {
        ConfigCommand.MOTOR_SPEED: 50,
        ConfigCommand.MOTOR_CURRENT: b"\x10\x20",
    }


def test_parse_truncated_config_notification() -> None:
    assert parse_config_notification(bytes([0x00, 0x00, ConfigCommand.MOTOR_SPEED])) == {}
