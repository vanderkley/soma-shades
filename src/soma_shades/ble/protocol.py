"""Bluetooth LE protocol of the Soma Smart Shades 2 (V2).

The protocol is reverse engineered, see https://github.com/rzuppur/smart-shades-documentation for the documentation.
The Smart Shades 3 (V3) use another protocol, they are recognized but not supported.
"""

import uuid
from enum import IntEnum

from soma_shades.utils import to_snake_case

ADVERTISEMENT_NAME = "S"  # local name in the advertisement data of a V2 shade, V3 shades have no name
MANUFACTURER_ID = 880  # Wazombi Labs
V3_MIN_VERSION = 0x10  # the first byte of the manufacturer data is the version

# GATT characteristics
NAME_CHAR = uuid.UUID("00001892-b87f-490c-92cb-11ba5ea5167c")
MANUFACTURER_CHAR = uuid.UUID("00002a29-0000-1000-8000-00805f9b34fb")
SERIAL_NR_CHAR = uuid.UUID("00002a25-0000-1000-8000-00805f9b34fb")
POSITION_CHAR = uuid.UUID("00001525-b87f-490c-92cb-11ba5ea5167c")
MOVE_PERCENT_CHAR = uuid.UUID("00001526-b87f-490c-92cb-11ba5ea5167c")  # target position
MOTOR_CHAR = uuid.UUID("00001530-b87f-490c-92cb-11ba5ea5167c")
NOTIFY_CHAR = uuid.UUID("00001531-b87f-490c-92cb-11ba5ea5167c")  # identify, plays a sound
GROUP_CHAR = uuid.UUID("00001893-b87f-490c-92cb-11ba5ea5167c")
CALIBRATE_CHAR = uuid.UUID("00001529-b87f-490c-92cb-11ba5ea5167c")
CHARGING_CHAR = uuid.UUID("00001894-b87f-490c-92cb-11ba5ea5167c")  # input voltage and charging current
CONFIG_CHAR = uuid.UUID("00001896-b87f-490c-92cb-11ba5ea5167c")
BATTERY_LEVEL_CHAR = uuid.UUID("00002a19-0000-1000-8000-00805f9b34fb")
BATTERY_VOLTAGE_CHAR = uuid.UUID("0000ba71-b87f-490c-92cb-11ba5ea5167c")  # battery voltage in mV / 10
TIME_CHAR = uuid.UUID("00001555-b87f-490c-92cb-11ba5ea5167c")  # UNIX timestamp, writable
FIRMWARE_VERSION_CHAR = uuid.UUID("00002a26-0000-1000-8000-00805f9b34fb")
HARDWARE_VERSION_CHAR = uuid.UUID("00002a27-0000-1000-8000-00805f9b34fb")
SOFTWARE_VERSION_CHAR = uuid.UUID("00002a28-0000-1000-8000-00805f9b34fb")

# the battery voltage range of the Soma app: empty at 3.6 V, full at 4.1 V
BATTERY_EMPTY_VOLTAGE = 3600
BATTERY_FULL_VOLTAGE = 4100


def battery_level_from_voltage(voltage: int) -> int:
    """Convert the battery voltage in mV to a battery level from 0 to 100 percent."""
    level = (voltage - BATTERY_EMPTY_VOLTAGE) * 100 // (BATTERY_FULL_VOLTAGE - BATTERY_EMPTY_VOLTAGE)
    return max(0, min(100, level))


class SoundCommand(IntEnum):
    BEEP = 0x01


class MotorCommand(IntEnum):
    STOP = 0x00
    STOP_AT_NEXT_STEP = 0x01
    STOP_AT_NEXT_STEP_STATE = 0x03
    STEP_UP = 0x68
    UP = 0x69
    STEP_DOWN = 0x86
    DOWN = 0x96
    LOW_BATTERY = 0xFF


class MotorTriggerCommand(IntEnum):
    ADD = 0x13
    REMOVE = 0x23
    READ = 0x33
    EDIT = 0x43
    CLEAR_ALL = 0x63


class ConfigCommand(IntEnum):
    MOTOR_SPEED = 1
    MOTOR_DIRECTION = 2
    MOTOR_SPEED_TRIGGER = 3
    PID = 4
    GEO_POSITION = 5
    LOCAL_TIME_OFFSET = 6
    MOTOR_ACCELERATION = 7
    MOTOR_DECELERATION = 8
    MOTOR_USTALL_ACCELERATION = 9
    INCREASE_ENCODER_BY2 = 10
    INCREASE_ENCODER_BY4 = 11
    BOOT_SEQ = 12
    RESET_REASON = 13
    STOP_REASON = 14
    POF_COUNT = 15
    SLIP_LENGTH = 16
    ENC_MAX = 17
    ENC_CUR = 18
    SLIP_INTERVAL = 19
    POSITION_MOVE_TOTAL = 20
    MOTOR_MOVE_TOTAL = 21
    IN_CALIBRATION_MODE = 22
    SUNRISE_SUNSET = 23
    MOTOR_CURRENT = 24
    QUERY = 255


def parse_version(manufacturer_data: dict[int, bytes]) -> int | None:
    """The protocol version from the manufacturer data of the advertisement, None for other devices."""
    data = manufacturer_data.get(MANUFACTURER_ID)
    return data[0] if data else None


def is_v3_shade(manufacturer_data: dict[int, bytes]) -> bool:
    version = parse_version(manufacturer_data)
    return version is not None and version >= V3_MIN_VERSION


def parse_device_name(manufacturer_data: dict[int, bytes]) -> str:
    """Extract the shade name, as configured in the Soma app, from the manufacturer data of a V2 advertisement.

    The data is the version, an unknown byte, the current and target position, and the ASCII name followed by "0" and
    padded with spaces.
    """
    name = manufacturer_data.get(MANUFACTURER_ID, b"")[4:].decode("ascii", errors="ignore").rstrip()
    return to_snake_case(name.removesuffix("0").rstrip())


def parse_config_notification(data: bytes) -> dict[ConfigCommand, int | bytes]:
    """Parse a config notification: a 2 byte header followed by (command, length, value) records.

    Values of a single byte are returned as int.
    """
    result: dict[ConfigCommand, int | bytes] = {}
    offset = 2
    while offset + 1 < len(data):
        command, length = data[offset], data[offset + 1]
        offset += 2
        value = bytes(data[offset : offset + length])
        result[ConfigCommand(command)] = value[0] if length == 1 else value
        offset += length
    return result
