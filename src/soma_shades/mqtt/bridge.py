import asyncio
import functools
import json
import logging
import signal
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, NamedTuple, TypeVar

import aiomqtt
from prettytable import PrettyTable

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.mqtt.config import BridgeConfig
from soma_shades.mqtt.topics import (
    BRIDGE_AVAILABILITY_TOPIC,
    DISCOVER_TOPIC,
    HOME_ASSISTANT_STATUS_TOPIC,
    SMARTSHADE_TOPIC,
    SMARTSHADE_TOPIC_PATTERN,
    SUBSCRIPTIONS,
    CoverAvailability,
    CoverSet,
    CoverState,
    HomeAssistantStatus,
    button_config_topic,
    sensor_config_topic,
    shade_topic,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Sensor(NamedTuple):
    """A Home Assistant sensor of a shade, its state is published to the shade topic `key`."""

    key: str
    name: str
    device_class: str
    unit: str
    value: Callable[[ShadeClient], int | None]
    enabled_by_default: bool = True


SENSORS = [
    Sensor("battery", "Battery", "battery", "%", lambda shade: shade.battery_level),
    Sensor("battery_voltage", "Battery voltage", "voltage", "mV", lambda shade: shade.battery_voltage),
    # of the solar panel or USB charger, 0 without a charger
    Sensor("input_voltage", "Input voltage", "voltage", "mV", lambda shade: shade.input_voltage),
    # the unit is not certain, disabled by default
    Sensor(
        "charging_current",
        "Charging current",
        "current",
        "mA",
        lambda shade: shade.charging_current,
        enabled_by_default=False,
    ),
]
# sensors of earlier versions, their retained messages are cleared so Home Assistant removes them
REMOVED_SENSORS = ["solar_panel"]


class MQTTBridge:
    """A bridge between the Soma smart shades and Home Assistant, through MQTT.

    Everything runs in a single asyncio event loop:
    - a connection task per shade keeps the Bluetooth connection alive and reconnects with an exponential backoff
    - the MQTT client receives the commands from Home Assistant and publishes the availability and state
    - periodic tasks log a status table and refresh the position and battery level
    """

    def __init__(self, fleet: ShadeFleet, config: BridgeConfig | None = None):
        self.fleet = fleet
        self.config = config or BridgeConfig()
        self.client: aiomqtt.Client | None = None
        self.mqtt_task: asyncio.Task[None] | None = None
        self.tasks: set[asyncio.Task[Any]] = set()
        self.connection_tasks: dict[str, asyncio.Task[None]] = {}  # Bluetooth connection task per shade name
        self.state_updates: asyncio.Queue[ShadeClient] = asyncio.Queue()
        self.availability: dict[str, str] = {}  # last availability status per shade name
        self.offline_timers: dict[str, asyncio.Task[None]] = {}  # reports a shade offline after the grace period
        self.connect_semaphore = asyncio.Semaphore(self.config.connect_concurrency)

    async def run(self, discover: bool = True) -> None:
        """Run the bridge until it is cancelled (Ctrl-C or SIGTERM), optionally discovering shades first."""
        if task := asyncio.current_task():
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)

        if discover:
            await self.discover_shades(self.config.discovery_scan_time)
        else:
            self.start_shade_connections()

        self.spawn(self.publish_state_updates(), name="publish_state_updates")
        if self.config.status_table_interval:
            self.spawn(self.run_periodically(self.log_status_table, self.config.status_table_interval), name="status")
        self.spawn(
            self.run_periodically(
                self.update_shades,
                self.config.update_interval,
                startup_delay=self.config.update_interval,  # the shades are updated when they connect
            ),
            name="update_shades",
        )
        self.mqtt_task = self.spawn(self.run_mqtt(), name="mqtt")
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            await self.shutdown()

    async def run_mqtt(self) -> None:
        """Connect to the MQTT broker and handle the incoming messages, reconnect when the connection is lost."""
        broker = f"{self.config.broker}:{self.config.port}"
        while True:
            logger.info(f"Connecting to broker {broker}...")
            # the broker reports the bridge offline when the connection is lost, which makes all shades unavailable
            will = aiomqtt.Will(BRIDGE_AVAILABILITY_TOPIC, CoverAvailability.OFFLINE, retain=True)
            try:
                async with aiomqtt.Client(
                    hostname=self.config.broker,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    will=will,
                ) as client:
                    self.client = client
                    logger.info(f"Connected to broker {broker}")
                    await self.publish(BRIDGE_AVAILABILITY_TOPIC, CoverAvailability.ONLINE)
                    for topic in SUBSCRIPTIONS:
                        await client.subscribe(topic)
                    await self.publish_all()
                    async for message in client.messages:
                        # handle each message in its own task, a Bluetooth command can take a while
                        self.spawn(self.handle_message(message), name=f"message {message.topic.value}")
            except aiomqtt.MqttError as err:
                logger.error(f"Connection error with broker {broker}: {err}, reconnecting in "
                             f"{self.config.mqtt_reconnect_interval:g} seconds...")  # fmt: skip
            finally:
                self.client = None
            await asyncio.sleep(self.config.mqtt_reconnect_interval)

    async def handle_message(self, message: aiomqtt.Message) -> None:
        """Handle an incoming MQTT message.

        When Home Assistant comes online, the discovery messages, availability and state of the shades are published
        again. Messages on the "/set" and "/set_position" topics control the shades.
        """
        topic = message.topic.value
        payload = message.payload.decode() if isinstance(message.payload, (bytes, bytearray)) else str(message.payload)
        logger.debug(f"Incoming MQTT message {topic} payload: {payload!r}")

        try:
            if topic == HOME_ASSISTANT_STATUS_TOPIC:
                await self.handle_home_assistant_status(HomeAssistantStatus(payload.lower()))
            elif topic == DISCOVER_TOPIC:
                try:
                    scan_for = min(float(payload), 30)
                except ValueError:
                    scan_for = 30
                await self.discover_shades(max(self.config.discovery_scan_time, scan_for))
            elif match := SMARTSHADE_TOPIC_PATTERN.match(topic):
                await self.handle_shade_command(match.group("device_name"), match.group("end_of_topic"), payload)
        except ValueError as err:
            logger.warning(f"Ignoring MQTT message {topic} with invalid payload {payload!r}: {err}")

    async def handle_home_assistant_status(self, status: HomeAssistantStatus) -> None:
        logger.info(f"Home Assistant status is {status.upper()}")
        if status == HomeAssistantStatus.ONLINE:
            if not self.fleet.shades:
                await self.discover_shades(self.config.discovery_scan_time)
            # the retained messages may be gone, e.g. after a restart of a broker without persistence
            await self.publish_all()

    async def handle_shade_command(self, device_name: str, end_of_topic: str, payload: str) -> None:
        if end_of_topic == "set":
            match CoverSet(payload.lower()):
                case CoverSet.OPEN:
                    await self.control_shade(device_name, ShadeClient.move_up)
                case CoverSet.CLOSE:
                    await self.control_shade(device_name, ShadeClient.move_down)
                case CoverSet.STOP:
                    await self.control_shade(device_name, ShadeClient.stop)
        elif end_of_topic == "set_position":
            target_position = int(payload)
            await self.control_shade(device_name, lambda shade: shade.set_position(target_position))
        elif end_of_topic == "sync_time":
            await self.control_shade(device_name, ShadeClient.sync_time)

    async def discover_shades(self, scan_for: float) -> None:
        """Discover shades via Bluetooth and keep a connection with each of them."""
        try:
            await self.fleet.discover(scan_for=scan_for)
        except Exception as err:
            logger.error(f"Bluetooth discovery error: {err!r}")
        self.start_shade_connections()
        await self.publish_all()  # announce newly discovered shades to Home Assistant

    def start_shade_connections(self) -> None:
        """Start a connection task for each shade that does not have one yet."""
        for shade in self.fleet.shades:
            if shade.name in self.connection_tasks:
                continue
            shade.on_update = functools.partial(self.state_updates.put_nowait, shade)
            self.connection_tasks[shade.name] = self.spawn(
                self.maintain_connection(shade), name=f"connection {shade.name}"
            )

    async def maintain_connection(self, shade: ShadeClient) -> None:
        """Keep the Bluetooth connection with a shade alive, reconnect with an exponential backoff.

        The shade is only reported offline when it cannot be reconnected within the grace period, which avoids a
        flapping availability in Home Assistant on short connection drops.
        """
        backoff = self.config.reconnect_backoff_min
        self.start_offline_timer(shade)
        while True:
            try:
                async with shade.lock:
                    await self.connect_shade(shade)
            except Exception as err:
                logger.warning(f"Cannot connect to {shade.name!r}, retry in {backoff:g} seconds: {err}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max)
                continue

            connected_since = time.monotonic()
            await self.keep_connection_alive(shade)
            self.start_offline_timer(shade)
            if time.monotonic() - connected_since >= self.config.stable_connection_time:
                backoff = self.config.reconnect_backoff_min
            else:
                # the shade drops the connection right away, don't hammer it with reconnects
                logger.warning(f"Connection to {shade.name!r} was unstable, reconnect in {backoff:g} seconds")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max)

    async def connect_shade(self, shade: ShadeClient) -> None:
        """Connect to a shade and initialize it, the caller must hold the shade lock."""
        if shade.is_connected():
            return

        async with self.connect_semaphore:
            await shade.connect(timeout=self.config.connect_timeout)

        try:
            # first connection: read the manufacturer etc. and identify the shade with a beep
            if not any([shade.manufacturer, shade.serial_number, shade.software_version]):
                await shade.get_info()
                self.fleet.save()
                await shade.identify()

            await shade.get_position()
            await shade.get_battery_level()
            await shade.start_notify("position")
            await shade.start_notify("battery_level")
        except Exception:
            # without notifications the state would go stale, so start over on the next attempt
            await shade.disconnect()
            raise
        await self.read_diagnostics(shade)

        if timer := self.offline_timers.pop(shade.name, None):
            timer.cancel()
        await self.publish_availability(shade, CoverAvailability.ONLINE)

    async def keep_connection_alive(self, shade: ShadeClient) -> None:
        """Wait until the shade disconnects, sending a keepalive request every interval.

        The shades drop a connection after 3 minutes without requests. A single read costs the shade less battery
        than reconnecting, which rediscovers the services, reads the state and subscribes to notifications again.
        """
        while True:
            try:
                # asyncio.timeout instead of wait_for, which can swallow a cancellation on Python 3.11
                async with asyncio.timeout(self.config.keepalive_interval):
                    await shade.wait_until_disconnected()
                return
            except TimeoutError:
                pass
            try:
                async with shade.lock:
                    if shade.is_connected():
                        await shade.keepalive()
            except Exception as err:
                logger.warning(f"Keepalive of {shade.name!r} failed: {err!r}")

    def start_offline_timer(self, shade: ShadeClient) -> None:
        """Report the shade offline when it is not connected again within the grace period."""

        async def report_offline() -> None:
            await asyncio.sleep(self.config.offline_grace_period)
            self.offline_timers.pop(shade.name, None)
            if not shade.is_connected():
                await self.publish_availability(shade, CoverAvailability.OFFLINE)

        if timer := self.offline_timers.get(shade.name):
            timer.cancel()
        self.offline_timers[shade.name] = self.spawn(report_offline(), name=f"offline timer {shade.name}")

    async def control_shade(self, device_name: str, command: Callable[[ShadeClient], Awaitable[None]]) -> None:
        """Run a command on a shade, connect first when the connection is lost."""
        shade = self.fleet.find(device_name)
        if not shade:
            logger.warning(f"Smart Shade {device_name!r} not found")
            return
        try:
            async with shade.lock:
                await self.connect_shade(shade)
                await command(shade)
        except Exception as err:
            logger.error(f"Cannot control shade {device_name!r}: {err!r}")

    async def update_shades(self) -> None:
        """Refresh the position and battery level of the connected shades, the connection tasks do the reconnects."""
        for shade in self.fleet.shades:
            if not shade.is_connected():
                continue
            try:
                async with shade.lock:
                    await shade.get_position()
                    await shade.get_battery_level()
                    await self.read_diagnostics(shade)
            except Exception as err:
                logger.error(f"Periodic update of {shade.name!r} failed: {err!r}")

    async def read_diagnostics(self, shade: ShadeClient) -> None:
        """Read the battery voltage and the charging input, which not every firmware may support."""
        for read in (shade.get_battery_voltage, shade.get_charging):
            try:
                await read()
            except Exception as err:
                logger.warning(f"Cannot read {read.__name__!r} of {shade.name!r}: {err!r}")

    def log_status_table(self) -> None:
        """Log a table with the availability and state of the shades."""
        table = PrettyTable(align="l")
        table.field_names = ["Shade", "MAC", "Availability", "Position", "State", "Battery", "Connected"]
        for shade in self.fleet.shades:
            table.add_row(
                [
                    shade.name,
                    shade.mac,
                    shade.availability_status,
                    "" if shade.position is None else f"{shade.position}%",
                    shade.cover_status or "",
                    "" if shade.battery_level is None else f"{shade.battery_level}%",
                    shade.connected_duration or "",
                ]
            )
        logger.info(f"\n{table}")

    async def publish(self, topic: str, payload: str | int | None) -> bool:
        """Publish a retained message, returns False when the bridge is not connected to the broker.

        All messages are retained: Home Assistant subscribes to the availability and state topics only after
        processing the discovery message and would miss them otherwise (the cover then stays unavailable), and it
        receives the discovery messages when it starts after the bridge.
        """
        if self.client is None:
            logger.debug(f"Not connected to the broker, dropped message {topic} payload: {payload!r}")
            return False
        try:
            await self.client.publish(topic, payload, qos=0, retain=True)
        except aiomqtt.MqttError as err:
            logger.warning(f"Cannot publish message {topic} payload: {payload!r}: {err}")
            return False
        return True

    async def publish_all(self) -> None:
        """Publish the discovery message, availability and state of all shades, e.g. after connecting to the broker."""
        for shade in self.fleet.shades:
            await self.publish_config(shade)
            if shade.name in self.availability:
                await self.publish_availability(shade, self.availability[shade.name], force=True)
            if shade.cover_status:
                await self.publish_state(shade)

    async def publish_availability(self, shade: ShadeClient, status: str, force: bool = False) -> None:
        """Publish whether a shade is "online" or "offline", unless that status was already published."""
        if not force and self.availability.get(shade.name) == status:
            return
        self.availability[shade.name] = status
        logger.info(f"Publishing {shade.name!r} availability {status}")
        await self.publish(shade_topic(shade.name, "availability"), CoverAvailability(status))

    async def publish_state_updates(self) -> None:
        """Publish the state of shades that reported a change."""
        while True:
            shade = await self.state_updates.get()
            await self.publish_state(shade)

    async def publish_state(self, shade: ShadeClient) -> None:
        battery = "unknown" if shade.battery_level is None else f"{shade.battery_level}%"
        logger.info(
            f"Publishing {shade.name!r} state {shade.cover_status} at position {shade.position}%, battery {battery}"
        )
        state = CoverState(shade.cover_status) if shade.cover_status else "unknown"
        await self.publish(shade_topic(shade.name, "state"), state)
        await self.publish(shade_topic(shade.name, "position"), shade.position)
        for sensor in SENSORS:
            if (value := sensor.value(shade)) is not None:
                await self.publish(shade_topic(shade.name, sensor.key), value)

    async def publish_config(self, shade: ShadeClient) -> None:
        """Publish the Home Assistant MQTT discovery messages of a shade, which create its cover, sensors and button."""
        # the entities are available when both the bridge and the shade are "online"
        availability = [
            {"topic": shade_topic(shade.name, "availability")},
            {"topic": BRIDGE_AVAILABILITY_TOPIC},
        ]
        device = {
            "name": shade.display_name,
            "model": "Smart Shades",
            # the serial number is a firmware build string, the same on every shade, so it is not an identifier
            "identifiers": [shade.mac],
            "connections": [["mac", shade.mac]],
            "manufacturer": shade.manufacturer,
            "hw_version": shade.hardware_version,
            "sw_version": shade.software_version,
        }
        cover_discovery_message = {
            "~": f"{SMARTSHADE_TOPIC}/{shade.name}",
            "name": None,  # the cover has the name of the device
            "unique_id": shade.name,
            "command_topic": "~/set",
            "state_topic": "~/state",
            "set_position_topic": "~/set_position",
            "position_topic": "~/position",
            "availability": availability,
            "availability_mode": "all",
            "position_open": 0,
            "position_closed": 100,
            "device": device,
        }
        logger.debug(f"Publishing {shade.name!r} discovery messages")
        await self.publish(shade_topic(shade.name, "config"), json.dumps(cover_discovery_message))

        for sensor in SENSORS:
            sensor_discovery_message = {
                "name": sensor.name,
                "unique_id": f"{shade.name}_{sensor.key}",
                "state_topic": shade_topic(shade.name, sensor.key),
                "device_class": sensor.device_class,
                "state_class": "measurement",
                "unit_of_measurement": sensor.unit,
                "entity_category": "diagnostic",
                "enabled_by_default": sensor.enabled_by_default,
                "availability": availability,
                "availability_mode": "all",
                "device": device,
            }
            await self.publish(sensor_config_topic(shade.name, sensor.key), json.dumps(sensor_discovery_message))
        for key in REMOVED_SENSORS:
            await self.publish(sensor_config_topic(shade.name, key), None)
            await self.publish(shade_topic(shade.name, key), None)

        # sets the clock of the shade, which drifts fast, for the schedules of the Soma app
        sync_time_discovery_message = {
            "name": "Sync time",
            "unique_id": f"{shade.name}_sync_time",
            "command_topic": shade_topic(shade.name, "sync_time"),
            "entity_category": "config",
            "icon": "mdi:clock-check-outline",
            "availability": availability,
            "availability_mode": "all",
            "device": device,
        }
        await self.publish(button_config_topic(shade.name, "sync_time"), json.dumps(sync_time_discovery_message))

    async def run_periodically(
        self, func: Callable[[], Awaitable[None] | None], interval: float, startup_delay: float = 0
    ) -> None:
        """Call a function or coroutine function every `interval` seconds."""
        await asyncio.sleep(startup_delay)
        while True:
            try:
                result = func()
                if isinstance(result, Awaitable):
                    await result
            except Exception as err:
                logger.error(f"Periodic task {func.__name__!r} failed: {err!r}")
            await asyncio.sleep(interval)

    def spawn(self, coro: Coroutine[Any, Any, T], name: str) -> asyncio.Task[T]:
        """Run a coroutine in a background task, keeping a reference so it is not garbage collected."""
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and (err := task.exception()):
            logger.error(f"Task {task.get_name()!r} failed: {err!r}")

    async def shutdown(self) -> None:
        """Stop the background tasks, report the shades offline and disconnect them, then disconnect from the broker."""
        tasks = [task for task in self.tasks if task is not self.mqtt_task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        for shade in self.fleet.shades:
            await self.publish_availability(shade, CoverAvailability.OFFLINE)
            try:
                async with asyncio.timeout(self.config.connect_timeout):
                    await shade.disconnect()
            except Exception as err:
                logger.warning(f"Cannot disconnect from {shade.name!r}: {err!r}")

        await self.publish(BRIDGE_AVAILABILITY_TOPIC, CoverAvailability.OFFLINE)
        if self.mqtt_task:
            self.mqtt_task.cancel()
            await asyncio.gather(self.mqtt_task, return_exceptions=True)
        logger.info("Bridge stopped")
