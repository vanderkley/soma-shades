from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import click

from soma_shades.ble.client import ShadeClient
from soma_shades.ble.fleet import ShadeFleet
from soma_shades.cli.options import cache_file_option, run_async, timeout_option

ACTIONS: dict[str, Callable[[ShadeClient, str], Awaitable[Any]]] = {
    "up": lambda shade, _: shade.move_up(),
    "down": lambda shade, _: shade.move_down(),
    "stop": lambda shade, _: shade.stop(),
    "set_position": lambda shade, value: shade.set_position(value),
    "position": lambda shade, _: shade.get_position(),
    "info": lambda shade, _: shade.get_info(),
    "battery": lambda shade, _: shade.get_battery_level(),
    "battery_voltage": lambda shade, _: shade.get_battery_voltage(),
    "solar_panel": lambda shade, _: shade.get_light_and_panel(),
    "motor_speed": lambda shade, _: shade.get_motor_speed(),
    "set_motor_speed": lambda shade, value: shade.set_motor_speed(value),
    "beep": lambda shade, _: shade.identify(),
    "sync_time": lambda shade, _: shade.sync_time(),
}
VALUE_ACTIONS = {"set_position", "set_motor_speed"}


@click.command()
@click.argument("shade_name")
@click.argument("action", type=click.Choice(sorted(ACTIONS)))
@click.argument("value", required=False)
@timeout_option
@cache_file_option
def control(shade_name: str, action: str, value: str | None, timeout: float, cache_file: Path | None) -> None:
    """Run an ACTION on the shade SHADE_NAME.

    VALUE is the position or motor speed (0 to 100) of the set_position and set_motor_speed actions.
    """
    if action in VALUE_ACTIONS and value is None:
        raise click.UsageError(f"The {action} action requires a VALUE")

    async def _control() -> None:
        fleet = ShadeFleet(cache_file)
        shade = fleet.get(shade_name)
        await shade.connect(timeout=timeout)
        try:
            result = await ACTIONS[action](shade, value or "")
            if action == "info":
                fleet.save()
            if result is not None:
                click.echo(result)
        finally:
            await shade.disconnect()

    run_async(_control())
