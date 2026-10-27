from pathlib import Path

import click

from soma_shades.ble.fleet import ShadeFleet
from soma_shades.cli.options import cache_file_option, run_async


@click.command()
@click.option("--scan-for", type=float, default=20, show_default=True, help="Scan duration in seconds.")
@click.option("--use-bdaddr", is_flag=True, help="macOS: use the Bluetooth address instead of a UUID.")
@cache_file_option
def discover(scan_for: float, use_bdaddr: bool, cache_file: Path | None) -> None:
    """Discover Soma Smart Shades and add them to the cache."""

    async def _discover() -> None:
        fleet = ShadeFleet(cache_file)
        await fleet.discover(scan_for=scan_for, use_bdaddr=use_bdaddr)
        for shade in fleet.shades:
            click.echo(f"{shade.name:20} {shade.mac}")

    run_async(_discover())
