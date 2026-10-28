import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from soma_shades import __version__
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.ble.protocol import MOVE_PERCENT_CHAR, NOTIFY_CHAR
from soma_shades.cli import hide_bluez_version_warning, main
from tests.conftest import FakeBluetooth


@pytest.fixture
def cache_file(fleet: ShadeFleet) -> Path:
    return fleet.cache_file


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_control_set_position(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    result = CliRunner().invoke(main, ["control", "Living Room", "set_position", "40", "--cache-file", str(cache_file)])
    assert result.exit_code == 0, result.output
    assert bluetooth.client.writes == [(MOVE_PERCENT_CHAR, bytes([40]))]
    assert not bluetooth.client.is_connected


def test_control_position_prints_the_result(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    result = CliRunner().invoke(main, ["control", "living_room", "position", "--cache-file", str(cache_file)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "100"


def test_control_requires_a_value(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    result = CliRunner().invoke(main, ["control", "living_room", "set_position", "--cache-file", str(cache_file)])
    assert result.exit_code == 2
    assert "requires a VALUE" in result.output
    assert bluetooth.clients == []


def test_control_unknown_shade(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    result = CliRunner().invoke(main, ["control", "kitchen", "up", "--cache-file", str(cache_file)])
    assert result.exit_code == 1
    assert "'kitchen' not found" in result.output


def test_cache_file_from_environment(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    result = CliRunner().invoke(main, ["control", "living_room", "beep"], env={"SOMA_CACHE_FILE": str(cache_file)})
    assert result.exit_code == 0, result.output
    assert bluetooth.client.writes == [(NOTIFY_CHAR, b"\x01")]


def test_probe_sounds(cache_file: Path, bluetooth: FakeBluetooth) -> None:
    args = ["probe-sounds", "living_room", "--start", "0x10", "--end", "0x12", "--delay", "0.01"]
    result = CliRunner().invoke(main, [*args, "--cache-file", str(cache_file)])
    assert result.exit_code == 0, result.output
    assert [data for _, data in bluetooth.client.writes] == [b"\x10", b"\x11", b"\x12"]
    assert "playing 0x12" in result.output


def test_probe_sounds_rejects_invalid_codes(cache_file: Path) -> None:
    result = CliRunner().invoke(
        main, ["probe-sounds", "living_room", "--start", "0x100", "--cache-file", str(cache_file)]
    )
    assert result.exit_code == 2
    assert "outside the range" in result.output


def test_bluez_version_warning_is_hidden() -> None:
    def record(message: str) -> logging.LogRecord:
        return logging.LogRecord("root", logging.WARNING, __file__, 0, message, None, None)

    assert not hide_bluez_version_warning(
        record("Could not determine BlueZ version, bluetoothctl not available, assuming 5.55+")
    )
    assert hide_bluez_version_warning(record("Cannot connect to 'living_room'"))
