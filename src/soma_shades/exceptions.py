class SomaShadesError(Exception):
    """Base class of all soma-shades errors."""


class ShadeNotFoundError(SomaShadesError):
    """The shade is not in the shades cache, run a discovery first."""


class ShadeDiscoveryError(SomaShadesError):
    """The Bluetooth device of the shade cannot be found."""


class ShadeConnectionError(SomaShadesError):
    """Connecting to the shade failed or timed out."""


class ShadeNotConnectedError(SomaShadesError):
    """The shade is not connected."""


class InvalidValueError(SomaShadesError, ValueError):
    """An invalid value, e.g. a position outside the range of 0 to 100."""
