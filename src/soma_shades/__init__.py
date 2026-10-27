"""Control Soma Smart Shades over Bluetooth LE, and bridge them to Home Assistant through MQTT."""

from importlib.metadata import PackageNotFoundError, version

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.exceptions import (
    InvalidValueError,
    ShadeConnectionError,
    ShadeDiscoveryError,
    ShadeNotConnectedError,
    ShadeNotFoundError,
    SomaShadesError,
)

try:
    __version__ = version("soma-shades")
except PackageNotFoundError:  # not installed
    __version__ = "0.0.0"

__all__ = [
    "InvalidValueError",
    "ShadeClient",
    "ShadeConnectionError",
    "ShadeDiscoveryError",
    "ShadeFleet",
    "ShadeNotConnectedError",
    "ShadeNotFoundError",
    "SomaShadesError",
    "__version__",
]
