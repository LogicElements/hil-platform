"""Base class of device drivers."""

import threading
from collections.abc import Collection, Mapping
from typing import ClassVar, NoReturn

from pydantic import BaseModel, ConfigDict

from hil.errors import ConfigError


class DriverConfig(BaseModel):
    """Base of driver-specific configuration models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Device:
    """One physical or simulated device declared in the station file.

    Constructing a device does no I/O; hardware is touched only in ``open``.
    ``open``, ``close`` and ``safe_state`` should raise ``DeviceError`` (or a subclass)
    on failure.
    """

    Config: ClassVar[type[DriverConfig]] = DriverConfig

    def __init__(self, name: str, config: DriverConfig) -> None:
        self.name = name
        self.config = config
        self.lock = threading.RLock()

    def dependencies(self) -> list[str]:
        """Names of devices that must exist and be opened before this one."""
        return []

    def bind(self, devices: Mapping[str, "Device"]) -> None:
        """Resolve references to other devices; called once all devices exist."""

    def channel_names(self) -> Collection[str]:
        return ()

    def resource(self, channel: str) -> object:
        """Return the resource object of ``channel``."""
        self._no_channel(channel)

    def _no_channel(self, channel: str) -> NoReturn:
        raise ConfigError(f"device {self.name!r} has no channel {channel!r}")

    def open(self) -> None:
        """Connect to the hardware."""

    def close(self) -> None:
        """Release the hardware."""

    def safe_state(self) -> None:
        """Switch every output of the device off."""
