from dataclasses import dataclass

from soma_shades.ble.connection import ConnectionConfig


@dataclass
class BridgeConfig(ConnectionConfig):
    """Settings of the MQTT bridge, all durations in seconds."""

    broker: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    mqtt_reconnect_interval: float = 5
    status_table_interval: float = 30  # log a status table of the shades, 0 disables it
    discovery_scan_time: float = 20  # Bluetooth scan for new shades, at startup and on the discover topic
    connect_concurrency: int = 1  # simultaneous Bluetooth connection attempts, including the initialization
