import pytest

from soma_shades.utils import default_cache_file, to_snake_case


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("LivingRoom", "living_room"),
        ("Living Room", "living_room"),
        ("living_room", "living_room"),
        ("Maurits  Room", "maurits_room"),
        ("kitchen", "kitchen"),
    ],
)
def test_to_snake_case(text: str, expected: str) -> None:
    assert to_snake_case(text) == expected


def test_default_cache_file() -> None:
    assert default_cache_file().name == "shades.json"
    assert "soma-shades" in default_cache_file().parts
