import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bleak.backends.device import BLEDevice

from soma_shades.ble.client import ShadeClient
from soma_shades.exceptions import ShadeConnectionError, ShadeDisabledError

logger = logging.getLogger(__name__)


@dataclass
class ConnectionConfig:
    """How the connection with a shade is kept alive, all durations in seconds."""

    # timeout of the scan for a shade that is not seen yet, and of disconnecting; a connection attempt has a fixed
    # timeout of 20 seconds in bleak-retry-connector
    connect_timeout: float = 15
    reconnect_backoff_min: float = 1
    reconnect_backoff_max: float = 5 * 60
    stable_connection_time: float = 60  # a connection lasting shorter does not reset the reconnect backoff
    keepalive_interval: float = 2 * 60  # the shades drop a connection 3 minutes after the last write
    update_interval: float = 15 * 60  # refresh the position, battery level and diagnostics of a connected shade
    offline_grace_period: float = 2 * 60  # only report a shade offline when reconnecting takes longer


class ShadeConnection:
    """Keep the connection with a shade open, for a fast response.

    A task reconnects a lost connection with an exponential backoff and sends a keepalive, used by the MQTT bridge and
    the Home Assistant integration. The shade is only reported offline when it cannot be reconnected within the grace
    period, which avoids a flapping availability on short connection drops.

    `find_device` returns the Bluetooth device before every connection attempt, for when another application manages
    the scanning. `on_first_connection` is called when the shade information is read for the first time.
    """

    def __init__(
        self,
        shade: ShadeClient,
        config: ConnectionConfig | None = None,
        connect_semaphore: asyncio.Semaphore | None = None,
        find_device: Callable[[str], BLEDevice | None] | None = None,
        on_availability: Callable[[bool], Awaitable[None]] | None = None,
        on_first_connection: Callable[[], Awaitable[None]] | None = None,
    ):
        self.shade = shade
        self.config = config or ConnectionConfig()
        self.online = False
        # the next shade connects after the initialization, the Bluetooth adapter of e.g. a Raspberry Pi fails the
        # service discovery and the reads (ATT error 0x0e) when a connection is set up at the same time
        self.connect_semaphore = connect_semaphore or asyncio.Semaphore(1)
        self.find_device = find_device
        self.on_availability = on_availability
        self.on_first_connection = on_first_connection
        self._task: asyncio.Task[None] | None = None
        self._offline_timer: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the connection task, unless it runs already or the Bluetooth connection of the shade is disabled."""
        if self.shade.bluetooth_enabled and self._task is None:
            self._task = asyncio.create_task(self._maintain(), name=f"connection {self.shade.name}")

    async def stop(self) -> None:
        """Stop the connection task, disconnect the shade and report it offline right away."""
        for task in (self._task, self._offline_timer):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._task = self._offline_timer = None
        try:
            async with asyncio.timeout(self.config.connect_timeout), self.shade.lock:  # waits for a running command
                await self.shade.disconnect()
        except Exception as err:
            logger.warning(f"Cannot disconnect from {self.shade.name!r}: {err!r}")
        await self._set_online(False)

    async def run_command(self, command: Callable[[], Awaitable[None]]) -> None:
        """Run a command on the shade, connect first when the connection is lost."""
        async with self.shade.lock:
            if not self.shade.bluetooth_enabled:
                raise ShadeDisabledError(f"The Bluetooth connection of {self.shade.name!r} is disabled")
            await self._connect()
            await command()

    async def _maintain(self) -> None:
        backoff = self.config.reconnect_backoff_min
        self._start_offline_timer()
        while True:
            try:
                async with self.shade.lock:
                    await self._connect()
            except Exception as err:
                logger.warning(f"Cannot connect to {self.shade.name!r}, retry in {backoff:g} seconds: {err}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max)
                continue

            connected_since = time.monotonic()
            await self._keep_alive()
            self._start_offline_timer()
            if time.monotonic() - connected_since >= self.config.stable_connection_time:
                backoff = self.config.reconnect_backoff_min
            else:
                # the shade drops the connection right away, don't hammer it with reconnects
                logger.warning(f"Connection to {self.shade.name!r} was unstable, reconnect in {backoff:g} seconds")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max)

    async def _connect(self) -> None:
        """Connect to the shade and initialize it, the caller must hold the shade lock."""
        shade = self.shade
        if shade.is_connected():
            return

        if self.find_device:
            shade.ble_device = self.find_device(shade.mac)
            if shade.ble_device is None:
                raise ShadeConnectionError(f"No Bluetooth adapter sees {shade.name!r}")

        async with self.connect_semaphore:
            await shade.connect(timeout=self.config.connect_timeout)

            try:
                if not any([shade.manufacturer, shade.serial_number, shade.software_version]):
                    await shade.get_info()
                    if self.on_first_connection:
                        await self.on_first_connection()

                await shade.get_position()
                await shade.get_battery_level()
                await shade.start_notify("position")
                await shade.start_notify("battery_level")
            except Exception:
                # without notifications the state would go stale, so start over on the next attempt
                await shade.disconnect()
                raise
            await self._read_diagnostics()

        if self._offline_timer:
            self._offline_timer.cancel()
            self._offline_timer = None
        await self._set_online(True)

    async def _keep_alive(self) -> None:
        """Wait until the shade disconnects, sending a keepalive request every interval.

        The shades drop a connection 3 minutes after the last write, reads do not count. A single write costs the
        shade less battery than reconnecting, which rediscovers the services, reads the state and subscribes to
        notifications again.
        """
        last_update = time.monotonic()
        while True:
            try:
                # asyncio.timeout instead of wait_for, which can swallow a cancellation on Python 3.11
                async with asyncio.timeout(self.config.keepalive_interval):
                    await self.shade.wait_until_disconnected()
                return
            except TimeoutError:
                pass
            try:
                async with self.shade.lock:
                    if not self.shade.is_connected():
                        continue
                    await self.shade.keepalive()
                    if time.monotonic() - last_update >= self.config.update_interval:
                        last_update = time.monotonic()
                        await self.shade.get_position()
                        await self.shade.get_battery_level()
                        await self._read_diagnostics()
            except Exception as err:
                logger.warning(f"Keepalive of {self.shade.name!r} failed: {err!r}")

    async def _read_diagnostics(self) -> None:
        """Read the battery voltage and the charging input, which not every firmware may support."""
        for read in (self.shade.get_battery_voltage, self.shade.get_charging):
            try:
                await read()
            except Exception as err:
                logger.warning(f"Cannot read {read.__name__!r} of {self.shade.name!r}: {err!r}")

    def _start_offline_timer(self) -> None:
        """Report the shade offline when it is not connected again within the grace period."""

        async def report_offline() -> None:
            await asyncio.sleep(self.config.offline_grace_period)
            self._offline_timer = None
            if not self.shade.is_connected():
                await self._set_online(False)

        if self._offline_timer:
            self._offline_timer.cancel()
        self._offline_timer = asyncio.create_task(report_offline(), name=f"offline timer {self.shade.name}")

    async def _set_online(self, online: bool) -> None:
        self.online = online
        if self.on_availability:
            await self.on_availability(online)
