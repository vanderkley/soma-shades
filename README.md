# soma-shades

[![CI](https://github.com/vanderkley/soma-shades/actions/workflows/ci.yml/badge.svg)](https://github.com/vanderkley/soma-shades/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/soma-shades)](https://pypi.org/project/soma-shades/)
[![Python](https://img.shields.io/pypi/pyversions/soma-shades)](https://pypi.org/project/soma-shades/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/vanderkley/soma-shades/blob/main/LICENSE)

Control [Soma Smart Shades](https://www.somasmarthome.com/) over Bluetooth LE, without the SOMA Connect hub, and
add them to Home Assistant through MQTT.

```
┌──────────────┐               ┌──────────────────────┐          ┌───────────┐          ┌────────────────┐
│ Soma Smart   │ Bluetooth LE  │ Soma Bridge          │   MQTT   │ Mosquitto │   MQTT   │ Home Assistant │
│ Shades       │◄─────────────►│ connection per shade │◄────────►│ broker    │◄────────►│                │
│              │               │ keepalive, reconnect │          │           │          │                │
└──────────────┘               └──────────────────────┘          └───────────┘          └────────────────┘
```

- **`soma` command line tool**: discover the shades, move them, read the position and battery level.
- **MQTT bridge**: the shades appear as covers in Home Assistant, with live position updates, battery and solar panel sensors.
- **Reliable connections**: keepalive, automatic reconnects, and no unavailable flapping on short connection drops.
- **Runs anywhere near the shades**: Docker image, or a systemd service on a Raspberry Pi.

Only the **SOMA Smart Shades 2** are supported. The Smart Shades 3 use a
[different protocol](https://github.com/rzuppur/smart-shades-documentation) and are planned for a next version.
This project is not affiliated with Soma.

## Quick start
Requirements: Python 3.11+, a Bluetooth LE adapter within range of the shades (Linux with BlueZ, or macOS), and for
Home Assistant an MQTT broker.

```bash
pip install soma-shades                     # or: uv tool install soma-shades

soma discover                               # find the shades, "Living Room" in the Soma app is living_room
soma control living_room down
soma control living_room set_position 50    # 0 is open, 100 is closed
soma bridge --broker 192.168.1.10           # bridge to Home Assistant
```
A shade accepts a single Bluetooth connection: close the Soma app and stop the bridge before using `soma control`.

## Home Assistant Integration
1. Install an MQTT broker: the
   [Mosquitto add-on](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md) on Home Assistant OS,
   or a Mosquitto container with the
   [Docker Compose file](https://github.com/vanderkley/soma-shades/blob/main/docker-compose.yml).
2. Add the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) with the address of the broker.
3. Start the bridge. Every shade appears as a device through MQTT discovery, with a cover, sensors for the battery
   level, battery voltage and solar panel voltage, and a *Sync time* button that sets the clock of the shade for the
   schedules of the Soma app. On the first connection the shade beeps once.

New shades are found when the bridge starts, or when you publish a scan duration in seconds while it runs:
```bash
mosquitto_pub -h <broker> -t homeassistant/cover/discover -m 20
```

To remove a shade, remove it from the cache file and delete the device in Home Assistant, which also clears its
retained discovery messages.

<details>
<summary>MQTT topics</summary>

| Topic                                                      | Direction | Payload                           |
|------------------------------------------------------------|-----------|-----------------------------------|
| `homeassistant/cover/smartshade/<shade>/config`            | publish   | discovery message                 |
| `homeassistant/cover/smartshade/<shade>/availability`      | publish   | `online`, `offline`               |
| `homeassistant/cover/smartshade/<shade>/state`             | publish   | `open`, `closed`, `opening`, ...  |
| `homeassistant/cover/smartshade/<shade>/position`          | publish   | `0` (open) to `100` (closed)      |
| `homeassistant/cover/smartshade/<shade>/battery`           | publish   | battery level, `0` to `100`       |
| `homeassistant/cover/smartshade/<shade>/battery_voltage`   | publish   | battery voltage in mV             |
| `homeassistant/cover/smartshade/<shade>/solar_panel`       | publish   | solar panel voltage in mV         |
| `homeassistant/sensor/smartshade/<shade>_<sensor>/config`  | publish   | discovery messages of the sensors |
| `homeassistant/button/smartshade/<shade>_sync_time/config` | publish   | discovery message of the button   |
| `homeassistant/cover/smartshade/bridge/availability`       | publish   | `online`, `offline` (last will)   |
| `homeassistant/cover/smartshade/<shade>/set`               | subscribe | `open`, `close`, `stop`           |
| `homeassistant/cover/smartshade/<shade>/set_position`      | subscribe | `0` to `100`                      |
| `homeassistant/cover/smartshade/<shade>/sync_time`         | subscribe | any payload sets the clock        |
| `homeassistant/cover/discover`                             | subscribe | scan duration in seconds (max 30) |
| `homeassistant/status`                                     | subscribe | `online` republishes all messages |

All published messages are retained, so Home Assistant also gets the covers when it starts after the bridge.
</details>

### How the bridge works
- Each shade has its own connection, reconnected with a backoff from 1 second up to 5 minutes.
- The shades drop idle connections after 3 minutes, so the bridge reads the battery every 2 minutes.
- A shade is only reported unavailable when it cannot be reconnected within 2 minutes.

## Running the bridge as a service

### Docker Compose
The [`docker-compose.yml`](https://github.com/vanderkley/soma-shades/blob/main/docker-compose.yml) runs Mosquitto
and the bridge. The bridge uses the Bluetooth of the host through D-Bus, so the host must be Linux with BlueZ. It
scans for shades when it starts, and uses the timezone of the host for the *Sync time* button.
```bash
curl -LO https://raw.githubusercontent.com/vanderkley/soma-shades/main/docker-compose.yml
mkdir -p deploy/mosquitto
curl -Lo deploy/mosquitto/mosquitto.conf \
    https://raw.githubusercontent.com/vanderkley/soma-shades/main/deploy/mosquitto/mosquitto.conf
docker compose up -d
docker compose logs -f soma-bridge
```

### Raspberry Pi with systemd
The [systemd unit](https://github.com/vanderkley/soma-shades/blob/main/deploy/systemd/soma-bridge@.service) runs the
bridge as your user, with the broker on `localhost`:
```bash
sudo apt-get install bluetooth pi-bluetooth pipx
sudo usermod -aG bluetooth $USER
pipx install soma-shades

sudo curl -Lo /etc/systemd/system/soma-bridge@.service \
    https://raw.githubusercontent.com/vanderkley/soma-shades/main/deploy/systemd/soma-bridge@.service
sudo systemctl daemon-reload
sudo systemctl enable --now soma-bridge@$USER
journalctl -u soma-bridge@$USER -f
```
For another broker, set `Environment=SOMA_BROKER=...` with `sudo systemctl edit soma-bridge@$USER`.

<details>
<summary>Mosquitto on Linux, without Docker</summary>

```bash
sudo apt-get install mosquitto mosquitto-clients
sudo tee /etc/mosquitto/conf.d/soma-shades.conf <<EOF
listener 1883 0.0.0.0
allow_anonymous true
EOF
sudo systemctl restart mosquitto
```
`allow_anonymous true` lets every host on the network connect. Only expose port 1883 on your local network, or
configure a password file and start the bridge with `--username` and `--password`.
</details>

## Command line

| Command                             | Description                                      |
|-------------------------------------|--------------------------------------------------|
| `soma discover`                     | Scan for shades and add them to the cache        |
| `soma control SHADE ACTION [VALUE]` | Run an action on a shade, see below              |
| `soma bridge`                       | Bridge the shades to Home Assistant through MQTT |
| `soma probe-sounds SHADE`           | Play the sound codes one by one                  |

Actions of `soma control`:
- Move: `up`, `down`, `stop`, `set_position VALUE` (0 is open, 100 is closed)
- Read: `position`, `battery`, `battery_voltage`, `solar_panel`, `motor_speed`, `info`
- Other: `set_motor_speed VALUE` (0 to 100), `sync_time`, `beep`

Run `soma COMMAND --help` for the options and `soma -v COMMAND` for debug logging. The options can also be set with
the environment variables `SOMA_CACHE_FILE`, `SOMA_BROKER`, `SOMA_PORT`, `SOMA_USERNAME`, `SOMA_PASSWORD` and
`SOMA_DISCOVER`.

<details>
<summary>Troubleshooting</summary>

Check the Bluetooth access on Linux:
```bash
ls -l /run/dbus/system_bus_socket     # the D-Bus socket exists
systemctl status bluetooth            # active (running)
bluetoothctl show                     # Powered: yes
```

| Error                             | Cause                                                                                |
|-----------------------------------|--------------------------------------------------------------------------------------|
| `FileNotFoundError`               | no D-Bus socket; in Docker, `/run/dbus` is not mounted                               |
| `AccessDenied`, `PermissionError` | D-Bus or AppArmor denies the access to BlueZ, or the user is not in `bluetooth`      |
| `No Bluetooth adapters found`     | `bluetoothd` runs without an adapter, check `bluetoothctl show` and `rfkill list`    |

- **A shade stays unavailable**: run `soma -v bridge` and look for `Cannot connect`. Check the range with
  `soma control <shade> battery` while the bridge is stopped.
- **The Home Assistant Bluetooth integration** competes for the same adapter. Give it a separate adapter, or disable
  it.
</details>

## Python API
```python
import asyncio

from soma_shades import ShadeFleet


async def main() -> None:
    fleet = ShadeFleet()  # the shades from the cache
    if not fleet.shades:
        await fleet.discover(scan_for=20)

    shade = fleet.get("living_room")
    await shade.connect(timeout=15)
    try:
        print(await shade.get_position(), await shade.get_battery_level())
        await shade.set_position(50)
    finally:
        await shade.disconnect()


asyncio.run(main())
```

## Development
See [CONTRIBUTING.md](https://github.com/vanderkley/soma-shades/blob/main/CONTRIBUTING.md) for the development setup,
the checks and the release steps.

## Credits
Thanks to [rzuppur/smart-shades-documentation](https://github.com/rzuppur/smart-shades-documentation) for the
protocol documentation, and [andersonshatch/soma-ctrl](https://github.com/andersonshatch/soma-ctrl) for the original
Node.js implementation.
Licensed under [MIT](https://github.com/vanderkley/soma-shades/blob/main/LICENSE).
