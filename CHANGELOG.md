# Changelog

All notable changes are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-10-28

### Added
- Sensors for every shade in Home Assistant: the battery level, the battery voltage and the solar panel voltage.
- A *Sync time* button in Home Assistant and a `sync_time` action of `soma control`, which set the clock of the shade
  for the schedules of the Soma app.
- A `battery_voltage` action of `soma control`.

### Changed
- The systemd unit is a template unit, `soma-bridge@.service`, that runs the bridge as the user of the instance:
  `systemctl enable --now soma-bridge@$USER`. Raspberry Pi OS has no default `pi` user anymore. Replace an installed
  `soma-bridge.service` with the new unit.

## [1.0.1] - 2026-10-28

### Fixed
- Every shade is a separate device in Home Assistant. The device identifier is the MAC address instead of the serial
  number, which is a firmware build string that is the same on every shade.
- The diagram in the README is shown on PyPI.

## [1.0.0] - 2026-10-27

First public release.

### Added
- `soma` command line tool with the `discover`, `control`, `bridge` and `probe-sounds` commands.
- MQTT bridge for Home Assistant, with MQTT discovery of the shades as covers.
- A connection task per shade that keeps the Bluetooth connection alive with a keepalive, and reconnects with an
  exponential backoff.
- Shades are reported offline only when they cannot be reconnected within a grace period.
- Bridge availability topic with an MQTT last will, all covers become unavailable when the bridge stops.
- Retained MQTT messages, Home Assistant gets the covers and their state also when it starts after the bridge.
- MQTT username and password, and environment variables for all bridge options.
- Docker image, Docker Compose file with Mosquitto, and a systemd unit.
- Python API: `ShadeClient` and `ShadeFleet`, with type hints.
- Python 3.11 and newer, so it runs on the Python of Raspberry Pi OS.

### Known limitations
- Only the Smart Shades 2 (V2 protocol) are supported. The Smart Shades 3 (V3 protocol) are recognized during the
  discovery, and skipped with a warning.
