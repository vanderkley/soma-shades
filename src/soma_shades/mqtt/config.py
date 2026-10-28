from dataclasses import dataclass


@dataclass
class BridgeConfig:
    """Settings of the MQTT bridge, all durations in seconds."""

    broker: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    mqtt_reconnect_interval: float = 5
    status_table_interval: float = 30  # log a status table of the shades, 0 disables it
    update_interval: float = 15 * 60  # refresh the position and battery level of the connected shades
    discovery_scan_time: float = 20  # Bluetooth scan for new shades, at startup and on the discover topic
    # timeout of the scan for a shade that is not seen yet, and of disconnecting; a connection attempt has a fixed
    # timeout of 20 seconds in bleak-retry-connector
    connect_timeout: float = 15
    connect_concurrency: int = 1  # simultaneous Bluetooth connection attempts, including the initialization
    reconnect_backoff_min: float = 1
    reconnect_backoff_max: float = 5 * 60
    stable_connection_time: float = 60  # a connection lasting shorter does not reset the reconnect backoff
    keepalive_interval: float = 2 * 60  # the shades drop a connection 3 minutes after the last write
    offline_grace_period: float = 2 * 60  # only report a shade offline when reconnecting takes longer
