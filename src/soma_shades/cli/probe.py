import asyncio
from pathlib import Path

import click

from soma_shades.ble.fleet import ShadeFleet
from soma_shades.cli.options import cache_file_option, run_async, timeout_option


def parse_byte(ctx: click.Context, param: click.Parameter, value: str) -> int:
    try:
        number = int(value, 0)  # accepts 16, 0x10 and 0b10000
    except ValueError:
        raise click.BadParameter(f"{value!r} is not a number") from None
    if not 0 <= number <= 0xFF:
        raise click.BadParameter(f"{value!r} is outside the range of 0x00 to 0xFF")
    return number


@click.command("probe-sounds")
@click.argument("shade_name")
@click.option("--start", default="0x02", callback=parse_byte, show_default=True, help="First code, 0x01 is the beep.")
@click.option("--end", default="0xFF", callback=parse_byte, show_default=True, help="Last code.")
@click.option("--delay", type=float, default=0, help="Seconds between the codes, 0 waits for Enter.")
@timeout_option
@cache_file_option
def probe_sounds(shade_name: str, start: int, end: int, delay: float, timeout: float, cache_file: Path | None) -> None:
    """Play the sound command codes START..END on SHADE_NAME, to find undocumented sounds.

    Prints each code before playing it. Without --delay it waits for Enter between the codes:
    Enter = next, r = repeat, q = quit. Stop the bridge first, a shade only accepts a single connection.
    """

    async def _probe() -> None:
        shade = ShadeFleet(cache_file).get(shade_name)
        code = start
        try:
            while code <= end:
                if not shade.is_connected():
                    await shade.connect(timeout=timeout)

                click.secho(f"\n>>> playing 0x{code:02X} ({code})", fg="yellow", bold=True)
                try:
                    await shade.identify(code)
                except Exception as err:
                    click.secho(f"    playing 0x{code:02X} failed: {err!r}", fg="red")

                if delay:
                    await asyncio.sleep(delay)
                    answer = ""
                else:
                    answer = (
                        (await asyncio.to_thread(input, "    [Enter] next, [r] repeat, [q] quit: ")).strip().lower()
                    )

                if answer == "q":
                    break
                if answer != "r":
                    code += 1
        finally:
            await shade.disconnect()

    try:
        run_async(_probe())
    except KeyboardInterrupt:
        pass
