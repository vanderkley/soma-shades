from pathlib import Path

import click

from soma_shades.ble.fleet import ShadeFleet
from soma_shades.cli.options import cache_file_option, run_async
from soma_shades.mqtt.bridge import MQTTBridge
from soma_shades.mqtt.config import BridgeConfig


@click.command()
@click.option("--broker", default="localhost", show_default=True, envvar="SOMA_BROKER", show_envvar=True,
              help="MQTT broker address.")  # fmt: skip
@click.option("--port", type=int, default=1883, show_default=True, envvar="SOMA_PORT", show_envvar=True,
              help="MQTT broker port.")  # fmt: skip
@click.option("--username", envvar="SOMA_USERNAME", show_envvar=True, help="MQTT username.")
@click.option("--password", envvar="SOMA_PASSWORD", show_envvar=True, help="MQTT password.")
@click.option("--discover/--no-discover", default=True, show_default=True, envvar="SOMA_DISCOVER", show_envvar=True,
              help="Scan for new shades at startup.")  # fmt: skip
@cache_file_option
def bridge(
    broker: str, port: int, username: str | None, password: str | None, discover: bool, cache_file: Path | None
) -> None:
    """Bridge the shades to Home Assistant through MQTT.

    The shades are announced with Home Assistant MQTT discovery and appear as covers.
    """
    config = BridgeConfig(broker=broker, port=port, username=username, password=password)
    mqtt_bridge = MQTTBridge(ShadeFleet(cache_file), config)
    try:
        run_async(mqtt_bridge.run(discover=discover))
    except KeyboardInterrupt:
        pass  # the bridge stopped itself
