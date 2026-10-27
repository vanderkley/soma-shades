import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, Self

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakNotFoundError, establish_connection

from soma_shades.ble.protocol import (
    BATTERY_LEVEL_CHAR,
    CHARGING_CHAR,
    CONFIG_CHAR,
    LIGHT_COEFF_TO_LUX,
    MOTOR_CHAR,
    MOVE_PERCENT_CHAR,
    NOTIFY_CHAR,
    POSITION_CHAR,
    ConfigCommand,
    MotorCommand,
    SoundCommand,
    parse_config_notification,
)
from soma_shades.exceptions import (
    InvalidValueError,
    ShadeConnectionError,
    ShadeDiscoveryError,
    ShadeNotConnectedError,
)
from soma_shades.utils import to_snake_case

logger = logging.getLogger(__name__)

Notification = Literal["position", "config", "battery_level"]
NOTIFICATION_CHARS = {
    "position": POSITION_CHAR,
    "config": CONFIG_CHAR,
    "battery_level": BATTERY_LEVEL_CHAR,
}


class ShadeClient:
    """A Soma smart shade with Bluetooth LE connectivity.

    A shade accepts a single connection and a single GATT operation at a time, hold `lock` while running a sequence
    of commands when multiple tasks use the same shade.
    """

    def __init__(
        self,
        mac: str,
        name: str,
        manufacturer: str | None = None,
        serial_number: str | None = None,
        firmware_version: str | None = None,
        software_version: str | None = None,
        hardware_version: str | None = None,
    ):
        self.mac = mac
        self.name = to_snake_case(name)
        self.manufacturer = manufacturer
        self.serial_number = serial_number
        self.firmware_version = firmware_version
        self.software_version = software_version
        self.hardware_version = hardware_version
        self.motor_speed: int | None = None
        self.battery_level: int | None = None
        self.charging_level: int | None = None
        self.solar_panel_level: int | None = None
        self._position: int | None = None
        self._target_position: int | None = None
        self._connected = False
        self.last_connect_time: datetime | None = None
        self.last_disconnect_time: datetime | None = None
        self.ble_device: BLEDevice | None = None
        self.ble_client: BleakClient | None = None
        self.lock = asyncio.Lock()
        self._disconnected = asyncio.Event()
        self._disconnected.set()
        # called whenever the position or target position changes, e.g. to publish the cover state
        self.on_update: Callable[[], None] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create a shade from a dict of `to_dict`, unknown keys are ignored."""
        keys = (
            "mac",
            "name",
            "manufacturer",
            "serial_number",
            "firmware_version",
            "software_version",
            "hardware_version",
        )
        return cls(**{key: data[key] for key in keys if key in data})

    def to_dict(self) -> dict[str, Any]:
        return {
            "mac": self.mac,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "serial_number": self.serial_number,
            "firmware_version": self.firmware_version,
            "software_version": self.software_version,
            "hardware_version": self.hardware_version,
        }

    @property
    def display_name(self) -> str:
        return " ".join(word.capitalize() for word in self.name.split("_"))

    @property
    def availability_status(self) -> str:
        return "online" if self.connected else "offline"

    @property
    def position(self) -> int | None:
        """The position from 0 (open) to 100 (closed)."""
        return self._position

    @property
    def cover_status(self) -> str | None:
        if self._position is None or self._target_position is None:
            return None
        if self._position == self._target_position == 0:
            return "open"
        if self._position == self._target_position == 100:
            return "closed"
        if self._position > self._target_position:
            return "opening"
        if self._position < self._target_position:
            return "closing"
        return "stopped"

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        if value:
            self.last_connect_time = datetime.now()
        else:
            self.last_disconnect_time = datetime.now()
        self._connected = value

    @property
    def connected_duration(self) -> str | None:
        if not self.last_connect_time:
            return None
        return str(datetime.now() - self.last_connect_time).split(".")[0]

    @property
    def _client(self) -> BleakClient:
        if self.ble_client is None:
            raise ShadeNotConnectedError(f"Shade {self.name!r} is not connected")
        return self.ble_client

    def is_connected(self) -> bool:
        return self.ble_client is not None and self.ble_client.is_connected

    async def wait_until_disconnected(self) -> None:
        await self._disconnected.wait()

    def _notify_update(self) -> None:
        if self.on_update:
            self.on_update()

    async def scan(self, timeout: float) -> BLEDevice:
        """Find the Bluetooth device of the shade."""
        logger.debug(f"Scanning for {self.name!r} BLE device...")
        # in active scanning mode, the scanner sends scan requests to the devices around it
        ble_device = await BleakScanner.find_device_by_address(self.mac, timeout=timeout, scanning_mode="active")
        if not ble_device:
            self.connected = False
            raise ShadeDiscoveryError(f"Cannot discover BLE device {self.name!r}, ensure the device is discoverable")
        return ble_device

    async def connect(self, timeout: float, max_attempts: int = 3) -> None:
        """Connect to the shade.

        The connection is established with bleak-retry-connector, which retries transient errors and works around
        BlueZ quirks, e.g. reusing a connection BlueZ still holds after a restart of this process. The connection
        stays open until `disconnect` is called or the connection is lost.

        How many connections can be active simultaneously, and whether connections can be active while scanning,
        depends on the Bluetooth adapter. Therefore, the device is only scanned for when it is not known yet.
        """
        if self.is_connected():
            logger.debug(f"Already connected to {self.name!r}")
            return

        # close a stale client before connecting again, the shade only accepts a single connection
        await self._close_client()

        if self.ble_device is None:
            self.ble_device = await self.scan(timeout)

        def _disconnect_callback(client: BleakClient) -> None:
            if client is not self.ble_client:
                return  # deliberate disconnect or a stale client
            logger.warning(f"Disconnected from {self.name!r}, duration: {self.connected_duration}")
            self.connected = False
            self.last_connect_time = None
            self._disconnected.set()

        logger.info(f"Connecting to {self.name!r} (MAC: {self.mac})...")
        try:
            self.ble_client = await establish_connection(
                BleakClient,
                self.ble_device,
                self.name,
                disconnected_callback=_disconnect_callback,
                max_attempts=max_attempts,
                timeout=timeout,
            )
        except BleakNotFoundError as err:
            self.connected = False
            self.ble_device = None  # rescan on the next attempt
            raise ShadeConnectionError(f"Connection to {self.name!r} timed out: {err}") from err
        except Exception as err:
            self.connected = False
            raise ShadeConnectionError(f"Cannot connect to {self.name!r}: {err}") from err

        self.connected = True
        self._disconnected.clear()
        logger.info(f"Connected to {self.name!r}")

    async def disconnect(self) -> None:
        await self._close_client()
        self.connected = False
        self.last_connect_time = None
        self._disconnected.set()
        logger.info(f"Disconnected from {self.name!r}")

    async def _close_client(self) -> None:
        """Disconnect the current client without triggering the disconnect callback."""
        client, self.ble_client = self.ble_client, None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as err:
            logger.debug(f"Error while closing the connection to {self.name!r}: {err!r}")

    async def get_info(self) -> None:
        """Read the device information (manufacturer, serial number, versions) and the battery level."""
        logger.info(f"Retrieving info for {self.name!r}...")
        client = self._client
        for service in client.services:
            description = service.description.lower()
            try:
                if description == "device information":
                    for char in service.characteristics:
                        value = (await client.read_gatt_char(char)).decode()
                        logger.debug(f"{char.description.replace(' String', '')}: {value}")
                        if "Manufacturer" in char.description:
                            self.manufacturer = value.strip()
                        elif "Serial Number" in char.description:
                            self.serial_number = value
                        elif "Hardware Revision" in char.description:
                            self.hardware_version = value
                        elif "Firmware Revision" in char.description:
                            self.firmware_version = value
                        elif "Software Revision" in char.description:
                            self.software_version = value
                elif description == "battery service":
                    for char in service.characteristics:
                        self.battery_level = int.from_bytes(await client.read_gatt_char(char), byteorder="little")
            except ValueError:
                continue

        logger.info(
            f"Info {self.name!r}, manufacturer {self.manufacturer}, serial no {self.serial_number}, "
            f"hw rev {self.hardware_version}, fw rev {self.firmware_version}, "
            f"software version {self.software_version}, battery {self.battery_level}%"
        )

    async def get_battery_level(self) -> int:
        response = await self._client.read_gatt_char(BATTERY_LEVEL_CHAR)
        self.battery_level = int.from_bytes(response, byteorder="little")
        logger.info(f"Shade {self.name!r} has {self.battery_level}% battery level")
        return self.battery_level

    async def keepalive(self) -> None:
        """Keep the connection alive, the shade drops a connection after 3 minutes without requests."""
        response = await self._client.read_gatt_char(BATTERY_LEVEL_CHAR)
        self.battery_level = int.from_bytes(response, byteorder="little")
        logger.debug(f"Keepalive {self.name!r}, {self.battery_level}% battery level")

    async def move_up(self) -> None:
        logger.info(f"Moving {self.name!r} up")
        self._target_position = 0
        self._notify_update()
        await self._client.write_gatt_char(MOTOR_CHAR, bytes([MotorCommand.UP]), response=True)

    async def move_down(self) -> None:
        logger.info(f"Moving {self.name!r} down")
        self._target_position = 100
        self._notify_update()
        await self._client.write_gatt_char(MOTOR_CHAR, bytes([MotorCommand.DOWN]), response=True)

    async def stop(self) -> None:
        logger.info(f"Stopping {self.name!r}")
        self._target_position = self._position
        await self._client.write_gatt_char(MOTOR_CHAR, bytes([MotorCommand.STOP]), response=True)
        self._notify_update()

    async def get_position(self) -> int:
        response = await self._client.read_gatt_char(MOVE_PERCENT_CHAR)
        self._target_position = int(response[0])
        response = await self._client.read_gatt_char(POSITION_CHAR)
        self._position = int(response[0])
        logger.info(f"Shade {self.name!r} {self.cover_status} at {self._position}%")
        self._notify_update()
        return self._position

    async def set_position(self, target: int | str) -> None:
        """Move to a position from 0 (open) to 100 (closed)."""
        try:
            target_value = int(target)
        except (TypeError, ValueError):
            raise InvalidValueError(f"The {self.name!r} position value {target!r} is invalid") from None
        if not 0 <= target_value <= 100:
            raise InvalidValueError(f"The {self.name!r} position value is outside the range of 0 to 100")

        self._target_position = target_value
        logger.info(f"Setting {self.name!r} target position to {target_value}% ({self.cover_status})")
        self._notify_update()
        await self._client.write_gatt_char(MOVE_PERCENT_CHAR, bytes([target_value]), response=True)

    async def start_notify(self, notification: Notification) -> None:
        """Subscribe to the position, config or battery level notifications of the shade."""
        if notification not in NOTIFICATION_CHARS:
            raise InvalidValueError(
                f"Invalid notification {notification!r}, choose from {', '.join(NOTIFICATION_CHARS)}"
            )

        async def _position_handler(_: BleakGATTCharacteristic, data: bytearray) -> None:
            self._position = int(data[0])
            logger.info(f"Received a position notification for {self.name!r}: {self._position}%")
            try:
                response = await self._client.read_gatt_char(MOVE_PERCENT_CHAR)
                self._target_position = int(response[0])
            except Exception as err:
                # the handler runs as a separate task, the connection may be gone by now
                logger.warning(f"Cannot read the {self.name!r} target position: {err!r}")
            self._notify_update()

        def _config_handler(_: BleakGATTCharacteristic, data: bytearray) -> None:
            for command, value in parse_config_notification(bytes(data)).items():
                if command == ConfigCommand.MOTOR_SPEED and isinstance(value, int):
                    self.motor_speed = value
                    logger.info(f"Received a motor speed notification for {self.name!r}: {value}%")
                else:
                    logger.info(f"Received a {command.name} config notification for {self.name!r}: {value!r}")

        def _battery_handler(_: BleakGATTCharacteristic, data: bytearray) -> None:
            self.battery_level = int.from_bytes(data, byteorder="little")
            logger.info(f"Received a battery level notification for {self.name!r}: {self.battery_level}%")

        handlers = {"position": _position_handler, "config": _config_handler, "battery_level": _battery_handler}
        await self._client.start_notify(NOTIFICATION_CHARS[notification], handlers[notification])
        logger.info(f"Subscribed for {self.name!r} on {notification!r} notifications")

    async def stop_notify(self, notification: Notification) -> None:
        if notification not in NOTIFICATION_CHARS:
            raise InvalidValueError(
                f"Invalid notification {notification!r}, choose from {', '.join(NOTIFICATION_CHARS)}"
            )
        await self._client.stop_notify(NOTIFICATION_CHARS[notification])
        logger.info(f"Unsubscribed for {self.name!r} from {notification!r} notifications")

    async def identify(self, sound: int = SoundCommand.BEEP) -> None:
        """Play a sound, the beep by default."""
        logger.info(f"Identifying {self.name!r} with sound 0x{sound:02X}")
        await self._client.write_gatt_char(NOTIFY_CHAR, bytes([sound]), response=True)

    async def get_motor_speed(self) -> int | None:
        await self.start_notify("config")
        logger.info(f"Querying the {self.name!r} motor speed")
        query = bytes([ConfigCommand.QUERY, 0x01, ConfigCommand.MOTOR_SPEED])
        await self._client.write_gatt_char(CONFIG_CHAR, query, response=True)
        await asyncio.sleep(1)  # give the shade time to answer through the config notification
        return self.motor_speed

    async def set_motor_speed(self, speed: int | str) -> None:
        try:
            speed_value = int(speed)
        except (TypeError, ValueError):
            raise InvalidValueError(f"The {self.name!r} motor speed value {speed!r} is invalid") from None
        if not 0 <= speed_value <= 100:
            raise InvalidValueError(f"The {self.name!r} motor speed value is outside the range of 0 to 100")

        self.motor_speed = speed_value
        logger.info(f"Setting {self.name!r} motor speed to {speed_value}%")
        command = bytes([ConfigCommand.MOTOR_SPEED, 0x01, speed_value])
        await self._client.write_gatt_char(CONFIG_CHAR, command, response=True)

    async def get_light_and_panel(self) -> tuple[int, int]:
        """Read the light level (lux) and solar panel level."""
        response = await self._client.read_gatt_char(CHARGING_CHAR)
        self.charging_level = int.from_bytes(response[:2], byteorder="little") * LIGHT_COEFF_TO_LUX
        self.solar_panel_level = int.from_bytes(response[2:4], byteorder="little")
        logger.info(
            f"Shade {self.name!r} charging level {self.charging_level} and solar panel level {self.solar_panel_level}"
        )
        return self.charging_level, self.solar_panel_level

    def __repr__(self) -> str:
        return (
            f"ShadeClient(name={self.name!r}, mac={self.mac!r}, cover_status={self.cover_status!r}, "
            f"battery_level={self.battery_level!r}, availability={self.availability_status!r})"
        )
