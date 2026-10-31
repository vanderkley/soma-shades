"""Control Soma Smart Shades over Bluetooth LE."""

from importlib.metadata import PackageNotFoundError, version

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.connection import ConnectionConfig, ShadeConnection
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.ble.protocol import ADVERTISEMENT_NAME, parse_device_name
from soma_shades.exceptions import (
    InvalidValueError,
    ShadeConnectionError,
    ShadeDisabledError,
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
    "ADVERTISEMENT_NAME",
    "ConnectionConfig",
    "InvalidValueError",
    "ShadeClient",
    "ShadeConnection",
    "ShadeConnectionError",
    "ShadeDisabledError",
    "ShadeDiscoveryError",
    "ShadeFleet",
    "ShadeNotConnectedError",
    "ShadeNotFoundError",
    "SomaShadesError",
    "__version__",
    "parse_device_name",
]
