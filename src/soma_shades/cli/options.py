import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import click

from soma_shades.exceptions import SomaShadesError
from soma_shades.utils import default_cache_file

cache_file_option = click.option(
    "--cache-file",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="SOMA_CACHE_FILE",
    show_envvar=True,
    help=f"File with the discovered shades.  [default: {default_cache_file()}]",
)

timeout_option = click.option(
    "--timeout", type=float, default=15, show_default=True, help="Bluetooth connection timeout in seconds."
)


def run_async(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine, show soma-shades errors as a CLI error message."""
    try:
        asyncio.run(coro)
    except SomaShadesError as err:
        raise click.ClickException(str(err)) from err
