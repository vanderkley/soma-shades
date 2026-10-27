# Changelog

All notable changes are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - Unreleased

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

### Known limitations
- Only the Smart Shades 2 (V2 protocol) are supported. The Smart Shades 3 (V3 protocol) are recognized during the
  discovery, and skipped with a warning.
