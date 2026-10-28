import asyncio
import json
import time
from datetime import datetime
from typing import Any

import aiomqtt
import pytest

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.protocol import (
    BATTERY_LEVEL_CHAR,
    BATTERY_VOLTAGE_CHAR,
    CHARGING_CHAR,
    MOTOR_CHAR,
    MOVE_PERCENT_CHAR,
    TIME_CHAR,
    MotorCommand,
)
from soma_shades.mqtt.bridge import MQTTBridge
from soma_shades.mqtt.topics import (
    BRIDGE_AVAILABILITY_TOPIC,
    button_config_topic,
    sensor_config_topic,
    shade_topic,
)
from tests.conftest import FakeBluetooth, mqtt_client, wait_until

AVAILABILITY = shade_topic("living_room", "availability")
STATE = shade_topic("living_room", "state")
BATTERY = shade_topic("living_room", "battery")


def message(topic: str, payload: str) -> aiomqtt.Message:
    return aiomqtt.Message(topic, payload.encode(), qos=0, retain=False, mid=0, properties=None)


async def start(bridge: MQTTBridge) -> None:
    bridge.spawn(bridge.publish_state_updates(), name="publish_state_updates")
    bridge.start_shade_connections()
    await wait_until(lambda: mqtt_client(bridge).payloads(AVAILABILITY) == ["online"])


async def test_discovery_message(bridge: MQTTBridge, shade: ShadeClient) -> None:
    await bridge.publish_config(shade)

    topic, payload, retain = mqtt_client(bridge).published[0]
    config: dict[str, Any] = json.loads(payload)
    assert topic == shade_topic("living_room", "config")
    assert retain
    assert config["unique_id"] == "living_room"
    assert config["name"] is None
    assert config["device"]["name"] == "Living Room"
    assert config["device"]["identifiers"] == [shade.mac]
    assert config["availability_mode"] == "all"
    assert {"topic": BRIDGE_AVAILABILITY_TOPIC} in config["availability"]


async def test_sensor_discovery_messages(bridge: MQTTBridge, shade: ShadeClient) -> None:
    await bridge.publish_config(shade)

    client = mqtt_client(bridge)
    cover_device = json.loads(client.payloads(shade_topic("living_room", "config"))[0])["device"]
    for sensor, device_class, unit in [
        ("battery", "battery", "%"),
        ("battery_voltage", "voltage", "mV"),
        ("input_voltage", "voltage", "mV"),
        ("charging_current", "current", "mA"),
    ]:
        topic = sensor_config_topic("living_room", sensor)
        assert topic == f"homeassistant/sensor/smartshade/living_room_{sensor}/config"
        config: dict[str, Any] = json.loads(client.payloads(topic)[0])
        assert config["unique_id"] == f"living_room_{sensor}"
        assert config["state_topic"] == shade_topic("living_room", sensor)
        assert config["device_class"] == device_class
        assert config["unit_of_measurement"] == unit
        assert config["device"] == cover_device  # the same device as the cover
        # the unit of the charging current is not certain
        assert config["enabled_by_default"] == (sensor != "charging_current")
        assert {"topic": BRIDGE_AVAILABILITY_TOPIC} in config["availability"]


async def test_removed_sensors_are_cleared(bridge: MQTTBridge, shade: ShadeClient) -> None:
    await bridge.publish_config(shade)

    # an empty retained message removes the sensor of an earlier version from Home Assistant
    assert mqtt_client(bridge).payloads(sensor_config_topic("living_room", "solar_panel")) == [None]


async def test_sync_time_button_discovery_message(bridge: MQTTBridge, shade: ShadeClient) -> None:
    await bridge.publish_config(shade)

    topic = button_config_topic("living_room", "sync_time")
    assert topic == "homeassistant/button/smartshade/living_room_sync_time/config"
    config: dict[str, Any] = json.loads(mqtt_client(bridge).payloads(topic)[0])
    assert config["unique_id"] == "living_room_sync_time"
    assert config["command_topic"] == shade_topic("living_room", "sync_time")


async def test_shades_with_the_same_serial_number_are_separate_devices(bridge: MQTTBridge) -> None:
    # the shades report a firmware build string as serial number, which is the same on every shade
    serial_number = "R-0103-kristjan-202303241235-5c2281a-6.1"
    for mac, name in [("AA:BB:CC:DD:EE:01", "Kitchen Door"), ("AA:BB:CC:DD:EE:02", "Kitchen Window")]:
        await bridge.publish_config(ShadeClient(mac=mac, name=name, serial_number=serial_number))

    devices = [
        json.loads(payload)["device"]
        for name in ("kitchen_door", "kitchen_window")
        for payload in mqtt_client(bridge).payloads(shade_topic(name, "config"))
    ]
    assert [device["identifiers"] for device in devices] == [["AA:BB:CC:DD:EE:01"], ["AA:BB:CC:DD:EE:02"]]


async def test_connects_and_publishes_the_state(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    # the state is published again on every update, e.g. of the battery level
    await wait_until(lambda: set(mqtt_client(bridge).payloads(STATE)) == {"closed"})
    assert set(mqtt_client(bridge).payloads(BATTERY)) == {90}
    assert mqtt_client(bridge).payloads(shade_topic("living_room", "battery_voltage"))[-1] == 3950
    assert mqtt_client(bridge).payloads(shade_topic("living_room", "input_voltage"))[-1] == 605
    assert mqtt_client(bridge).payloads(shade_topic("living_room", "charging_current"))[-1] == 615
    assert all(retain for *_, retain in mqtt_client(bridge).published)
    assert len(bluetooth.clients) == 1


async def test_short_connection_drop_is_not_reported(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    bluetooth.client.drop()
    await wait_until(lambda: len(bluetooth.clients) == 2)
    await asyncio.sleep(bridge.config.offline_grace_period * 1.5)

    assert mqtt_client(bridge).payloads(AVAILABILITY) == ["online"]


async def test_lost_shade_is_reported_offline_after_the_grace_period(
    bridge: MQTTBridge, bluetooth: FakeBluetooth
) -> None:
    await start(bridge)

    bluetooth.fail = True
    bluetooth.client.drop()
    await asyncio.sleep(bridge.config.offline_grace_period / 2)
    assert mqtt_client(bridge).payloads(AVAILABILITY) == ["online"]
    await wait_until(lambda: mqtt_client(bridge).payloads(AVAILABILITY) == ["online", "offline"])

    bluetooth.fail = False
    await wait_until(lambda: mqtt_client(bridge).payloads(AVAILABILITY) == ["online", "offline", "online"])


async def test_stuck_connection_attempt_is_reported_offline(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    bluetooth.hang = True
    bridge.start_shade_connections()
    await wait_until(lambda: mqtt_client(bridge).payloads(AVAILABILITY) == ["offline"])


async def test_keepalive_writes_the_clock(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    # the shades only count writes as activity, not reads
    await wait_until(lambda: [char for char, _ in bluetooth.client.writes].count(TIME_CHAR) >= 2)


async def test_missing_diagnostics_do_not_break_the_connection(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    bluetooth.missing = {BATTERY_VOLTAGE_CHAR, CHARGING_CHAR}

    await start(bridge)

    assert mqtt_client(bridge).payloads(shade_topic("living_room", "battery_voltage")) == []
    assert len(bluetooth.clients) == 1


async def test_sync_time_command(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    utc_offset = datetime.now().astimezone().utcoffset()
    assert utc_offset is not None
    before = time.time()
    await bridge.handle_message(message(shade_topic("living_room", "sync_time"), "PRESS"))

    char, data = bluetooth.client.writes[-1]
    assert char == TIME_CHAR
    # the clock of the shade is in local time
    local_time = int.from_bytes(data, "little") - utc_offset.total_seconds()
    assert int(before) <= local_time <= time.time()


async def test_shades_are_initialized_one_by_one(
    bridge: MQTTBridge, bluetooth: FakeBluetooth, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge.fleet.add(ShadeClient(mac="AA:BB:CC:DD:EE:02", name="Kitchen", manufacturer="Wazombi Labs"))
    events: list[str] = []
    connect, start_notify = ShadeClient.connect, ShadeClient.start_notify

    async def logged_connect(self: ShadeClient, timeout: float, max_attempts: int = 3) -> None:
        events.append(f"connect {self.name}")
        await connect(self, timeout, max_attempts)

    async def logged_start_notify(self: ShadeClient, notification: Any) -> None:
        await asyncio.sleep(0.01)  # the other connection task gets a chance to run
        events.append(f"notify {self.name}")
        await start_notify(self, notification)

    monkeypatch.setattr(ShadeClient, "connect", logged_connect)
    monkeypatch.setattr(ShadeClient, "start_notify", logged_start_notify)

    await start(bridge)
    await wait_until(lambda: len(events) == 6)

    # the second shade connects after both notifications of the first one
    assert events[1:3] == [f"notify {events[0].split()[1]}"] * 2
    assert events[3].startswith("connect")


async def test_unknown_position_is_not_published(bridge: MQTTBridge, shade: ShadeClient) -> None:
    # e.g. a battery level notification before the position is read
    shade.battery_level = 96

    await bridge.publish_state(shade)

    assert mqtt_client(bridge).payloads(STATE) == []
    assert mqtt_client(bridge).payloads(shade_topic("living_room", "position")) == []
    assert mqtt_client(bridge).payloads(BATTERY) == [96]


async def test_battery_level_change_is_published(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)
    await wait_until(lambda: mqtt_client(bridge).payloads(BATTERY)[-1:] == [90])

    bluetooth.client.notify_handlers[BATTERY_LEVEL_CHAR](None, bytearray([89]))

    await wait_until(lambda: mqtt_client(bridge).payloads(BATTERY)[-1:] == [89])


async def test_commands(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    await bridge.handle_message(message(shade_topic("living_room", "set_position"), "40"))
    await bridge.handle_message(message(shade_topic("living_room", "set"), "OPEN"))

    assert bluetooth.client.commands == [(MOVE_PERCENT_CHAR, bytes([40])), (MOTOR_CHAR, bytes([MotorCommand.UP]))]
    await wait_until(lambda: mqtt_client(bridge).payloads(STATE)[-1] == "opening")


async def test_command_reconnects_a_lost_shade(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)
    bridge.config.reconnect_backoff_min = 60  # the connection task waits, the command has to reconnect
    bluetooth.client.drop()

    await bridge.handle_message(message(shade_topic("living_room", "set"), "close"))

    assert bluetooth.client.commands == [(MOTOR_CHAR, bytes([MotorCommand.DOWN]))]


async def test_invalid_messages_are_ignored(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    await bridge.handle_message(message(shade_topic("living_room", "set"), "sideways"))
    await bridge.handle_message(message(shade_topic("living_room", "set_position"), "half"))
    await bridge.handle_message(message(shade_topic("unknown", "set"), "open"))
    await bridge.handle_message(message("homeassistant/status", "rebooting"))

    assert bluetooth.client.commands == []


async def test_home_assistant_online_republishes_everything(bridge: MQTTBridge) -> None:
    await start(bridge)
    mqtt_client(bridge).published.clear()

    await bridge.handle_message(message("homeassistant/status", "online"))

    topics = {topic for topic, *_ in mqtt_client(bridge).published}
    sensors = ("battery", "battery_voltage", "input_voltage", "charging_current")
    ends = ("config", "availability", "state", "position", *sensors, "solar_panel")  # solar_panel is cleared
    configs = {sensor_config_topic("living_room", sensor) for sensor in (*sensors, "solar_panel")}
    configs.add(button_config_topic("living_room", "sync_time"))
    assert topics == {shade_topic("living_room", end) for end in ends} | configs


async def test_shutdown_reports_everything_offline(bridge: MQTTBridge, bluetooth: FakeBluetooth) -> None:
    await start(bridge)

    await bridge.shutdown()

    assert mqtt_client(bridge).payloads(AVAILABILITY)[-1] == "offline"
    assert mqtt_client(bridge).payloads(BRIDGE_AVAILABILITY_TOPIC) == ["offline"]
    assert not bluetooth.client.is_connected
    assert not bridge.tasks
