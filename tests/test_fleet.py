from pathlib import Path
from typing import Any

import pytest
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.ble.protocol import MANUFACTURER_ID
from soma_shades.exceptions import ShadeNotFoundError
from tests.test_protocol import v2_manufacturer_data


def test_save_and_load(tmp_path: Path) -> None:
    cache_file = tmp_path / "subdir" / "shades.json"
    fleet = ShadeFleet(cache_file)
    assert fleet.shades == []

    assert fleet.add(ShadeClient(mac="AA:BB", name="Living Room", serial_number="123"))
    assert not fleet.add(ShadeClient(mac="AA:BB", name="Same MAC"))

    loaded = ShadeFleet(cache_file).shades
    assert [shade.to_dict() for shade in loaded] == [shade.to_dict() for shade in fleet.shades]


def test_corrupted_cache_file(tmp_path: Path) -> None:
    cache_file = tmp_path / "shades.json"
    cache_file.write_text("{not json")
    assert ShadeFleet(cache_file).shades == []


def test_find_and_get(tmp_path: Path) -> None:
    fleet = ShadeFleet(tmp_path / "shades.json")
    fleet.add(ShadeClient(mac="AA:BB", name="living_room"))

    assert fleet.get("Living Room").mac == "AA:BB"
    assert fleet.find("kitchen") is None
    with pytest.raises(ShadeNotFoundError):
        fleet.get("kitchen")


async def test_discover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def advertisement(name: str | None, manufacturer_data: dict[int, bytes]) -> AdvertisementData:
        return AdvertisementData(name, manufacturer_data, {}, [], None, -60, ())

    devices = {
        "AA:BB": (BLEDevice("AA:BB", "S", None), advertisement("S", v2_manufacturer_data("Living Room"))),
        "CC:DD": (BLEDevice("CC:DD", "S", None), advertisement("S", v2_manufacturer_data("Kitchen"))),
        "EE:FF": (BLEDevice("EE:FF", "Phone", None), advertisement("Phone", {})),
        "11:22": (BLEDevice("11:22", None, None), advertisement(None, {MANUFACTURER_ID: bytes([0x10, 0x00, 0x32])})),
    }

    async def discover(**kwargs: Any) -> dict[str, tuple[BLEDevice, AdvertisementData]]:
        return devices

    monkeypatch.setattr(BleakScanner, "discover", discover)
    fleet = ShadeFleet(tmp_path / "shades.json")
    fleet.add(ShadeClient(mac="AA:BB", name="living_room"))

    new_shades = await fleet.discover(scan_for=1)

    assert [shade.name for shade in new_shades] == ["kitchen"]
    assert [shade.name for shade in fleet.shades] == ["living_room", "kitchen"]
    # the known shade gets the found device, it doesn't need to scan for it again
    assert fleet.shades[0].ble_device is devices["AA:BB"][0]
    assert [shade.name for shade in ShadeFleet(fleet.cache_file).shades] == ["living_room", "kitchen"]
    assert "Smart Shades 3 found at 11:22" in caplog.text
