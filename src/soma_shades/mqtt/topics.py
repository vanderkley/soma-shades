import re
from enum import StrEnum

HOME_ASSISTANT_STATUS_TOPIC = "homeassistant/status"
HOME_ASSISTANT_COVER_TOPIC = "homeassistant/cover"
DISCOVER_TOPIC = f"{HOME_ASSISTANT_COVER_TOPIC}/discover"
SMARTSHADE_TOPIC = f"{HOME_ASSISTANT_COVER_TOPIC}/smartshade"
BRIDGE_AVAILABILITY_TOPIC = f"{SMARTSHADE_TOPIC}/bridge/availability"
SMARTSHADE_TOPIC_PATTERN = re.compile(rf"^{SMARTSHADE_TOPIC}/(?P<device_name>[^/]+)/(?P<end_of_topic>[^/]+)$")
# the sensors and buttons of a shade have discovery messages of their own, their topics are next to the cover topics
SENSOR_TOPIC = "homeassistant/sensor/smartshade"
BUTTON_TOPIC = "homeassistant/button/smartshade"

# the topics the bridge subscribes to
SUBSCRIPTIONS = [
    HOME_ASSISTANT_STATUS_TOPIC,
    DISCOVER_TOPIC,
    f"{SMARTSHADE_TOPIC}/+/set",
    f"{SMARTSHADE_TOPIC}/+/set_position",
    f"{SMARTSHADE_TOPIC}/+/sync_time",
]


def shade_topic(shade_name: str, end_of_topic: str) -> str:
    return f"{SMARTSHADE_TOPIC}/{shade_name}/{end_of_topic}"


def sensor_config_topic(shade_name: str, sensor: str) -> str:
    return f"{SENSOR_TOPIC}/{shade_name}_{sensor}/config"


def button_config_topic(shade_name: str, button: str) -> str:
    return f"{BUTTON_TOPIC}/{shade_name}_{button}/config"


class HomeAssistantStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class CoverAvailability(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class CoverState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    OPENING = "opening"
    CLOSING = "closing"
    STOPPED = "stopped"


class CoverSet(StrEnum):
    OPEN = "open"
    CLOSE = "close"
    STOP = "stop"
