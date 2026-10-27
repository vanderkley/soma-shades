import re
from pathlib import Path

from platformdirs import user_data_path

APP_NAME = "soma-shades"


def to_snake_case(text: str) -> str:
    """Convert a camel case or spaced name to snake case, e.g. "LivingRoom" and "Living Room" to "living_room"."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    snake = re.sub(r"\s+", "_", snake)
    snake = re.sub(r"_{2,}", "_", snake)
    return snake.lower()


def default_cache_file() -> Path:
    """The default location of the shades cache, e.g. ~/.local/share/soma-shades/shades.json on Linux."""
    return user_data_path(APP_NAME) / "shades.json"
