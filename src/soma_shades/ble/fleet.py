import json
import logging
from pathlib import Path

from bleak import BleakScanner

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.protocol import ADVERTISEMENT_NAME, is_v3_shade, parse_device_name
from soma_shades.exceptions import ShadeNotFoundError
from soma_shades.utils import default_cache_file, to_snake_case

logger = logging.getLogger(__name__)


class ShadeFleet:
    """The known shades, discovered via Bluetooth and stored in a cache file."""

    def __init__(self, cache_file: Path | None = None):
        self.cache_file = cache_file or default_cache_file()
        self.shades: list[ShadeClient] = self.load()

    async def discover(self, scan_for: float = 10.0, use_bdaddr: bool = False) -> list[ShadeClient]:
        """Discover nearby shades via Bluetooth, add the new ones to the cache and return them.

        The known shades get the found Bluetooth device, so they don't need to scan for it again when connecting.
        On macOS, devices are identified by a UUID unless `use_bdaddr` is set. Other platforms always use the
        Bluetooth address.
        """
        logger.info(f"Scanning Bluetooth devices for {scan_for:g} seconds...")
        devices = await BleakScanner.discover(timeout=scan_for, return_adv=True, cb={"use_bdaddr": use_bdaddr})

        new_shades: list[ShadeClient] = []
        for address, (ble_device, advertisement_data) in devices.items():
            logger.debug(f"Bluetooth device: {ble_device}, RSSI: {advertisement_data.rssi}, Adv: {advertisement_data}")
            if is_v3_shade(advertisement_data.manufacturer_data):
                logger.warning(f"Smart Shades 3 found at {address}, the V3 protocol is not supported yet")
                continue
            if advertisement_data.local_name != ADVERTISEMENT_NAME:
                continue

            name = parse_device_name(advertisement_data.manufacturer_data)
            logger.info(f"Smart Shade detected! - Name: {name}, MAC: {address}, RSSI: {advertisement_data.rssi}")
            shade = next((known for known in self.shades if known.mac == address), None)
            if shade is None:
                shade = ShadeClient(mac=address, name=name)
                self.add(shade)
                new_shades.append(shade)
            shade.ble_device = ble_device

        logger.info(f"{len(new_shades)} new Smart Shade(s) detected, {len(self.shades)} known")
        return new_shades

    def load(self) -> list[ShadeClient]:
        """Load the shades from the cache file."""
        if not self.cache_file.exists():
            return []
        try:
            data = json.loads(self.cache_file.read_text())
        except json.JSONDecodeError:
            logger.warning(f"Cache file {self.cache_file} is corrupted, starting with an empty shades list")
            return []
        shades = [ShadeClient.from_dict(shade_data) for shade_data in data]
        logger.debug(f"Loaded {len(shades)} cached Smart Shade(s) from {self.cache_file}")
        return shades

    def save(self) -> None:
        """Save the shades to the cache file."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps([shade.to_dict() for shade in self.shades], indent=2))
        logger.info(f"Saved {len(self.shades)} Smart Shade(s) to {self.cache_file}")

    def add(self, shade: ShadeClient) -> bool:
        """Add a shade unless a shade with the same MAC address is known, returns whether it was added."""
        if shade.mac in {known.mac for known in self.shades}:
            return False
        self.shades.append(shade)
        self.save()
        return True

    def find(self, name: str) -> ShadeClient | None:
        local_name = to_snake_case(name)
        return next((shade for shade in self.shades if shade.name == local_name), None)

    def get(self, name: str) -> ShadeClient:
        """Return the shade with the name, raises ShadeNotFoundError when it is not known."""
        shade = self.find(name)
        if shade is None:
            raise ShadeNotFoundError(f"Smart Shade {to_snake_case(name)!r} not found, run a discovery first")
        return shade
