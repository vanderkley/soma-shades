import logging

import click
import colorlog

from soma_shades import __version__
from soma_shades.cli.bridge import bridge
from soma_shades.cli.control import control
from soma_shades.cli.discover import discover
from soma_shades.cli.probe import probe_sounds


def hide_bluez_version_warning(record: logging.LogRecord) -> bool:
    """Hide the warning of bleak in the Docker image, which has no bluetoothctl to read the BlueZ version from.

    bleak then assumes BlueZ 5.55 or newer, which every supported system has. The warning is logged on the root logger,
    so it cannot be disabled with the log level of the bleak logger.
    """
    return not record.getMessage().startswith("Could not determine BlueZ version")


def setup_logging(verbose: bool) -> None:
    handler = colorlog.StreamHandler()
    if not verbose:
        handler.addFilter(hide_bluez_version_warning)
    # colors are disabled when the output is not a terminal, or with the NO_COLOR environment variable
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(asctime)s | %(log_color)s%(levelname)-7s%(reset)s | %(module)-8s | %(message)s",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
            stream=handler.stream,
        )
    )
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    logging.getLogger("soma_shades").setLevel(logging.DEBUG if verbose else logging.INFO)
    if verbose:
        # the connection attempts and retries
        logging.getLogger("bleak_retry_connector").setLevel(logging.DEBUG)


@click.group()
@click.version_option(__version__, prog_name="soma")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """Control Soma Smart Shades over Bluetooth LE, and bridge them to Home Assistant through MQTT."""
    setup_logging(verbose)


main.add_command(discover)
main.add_command(control)
main.add_command(bridge)
main.add_command(probe_sounds)
