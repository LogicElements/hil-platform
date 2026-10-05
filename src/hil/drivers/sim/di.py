"""Simulated digital input module."""

from collections.abc import Collection, Mapping

from pydantic import Field

from hil.config.refs import Ref
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import ConfigError, DeviceError
from hil.resources import DigitalInput, RelayChannel


class SimDiConfig(DriverConfig):
    inputs: int = Field(default=8, ge=1, le=256)
    # input index -> relay whose state the input reads (stimulus/response loopback)
    mirror: dict[int, Ref] = Field(default_factory=dict)


@register_driver("sim_di")
class SimDi(Device):
    """Inputs held in memory, settable from tests or mirroring simulated relays."""

    Config = SimDiConfig
    config: SimDiConfig

    def __init__(self, name: str, config: SimDiConfig) -> None:
        super().__init__(name, config)
        self.values = [False] * config.inputs
        self.is_open = False
        self._channels = frozenset(str(i) for i in range(config.inputs))
        self._mirror: dict[int, RelayChannel] = {}

    def dependencies(self) -> list[str]:
        return sorted({ref.device for ref in self.config.mirror.values()})

    def bind(self, devices: Mapping[str, Device]) -> None:
        for index, ref in self.config.mirror.items():
            if not 0 <= index < self.config.inputs:
                raise ConfigError(f"device {self.name!r}: mirror input {index} is out of range")
            resource = devices[ref.device].resource(ref.channel)
            if not isinstance(resource, RelayChannel):
                raise ConfigError(f"device {self.name!r}: mirror source {ref} is not a relay")
            self._mirror[index] = resource

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> DigitalInput:
        if channel not in self._channels:
            self._no_channel(channel)
        return DigitalInput(self, int(channel))

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def set_value(self, index: int, value: bool) -> None:
        with self.lock:
            self.values[index] = value

    def read(self, index: int) -> bool:
        with self.lock:
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            mirrored = self._mirror.get(index)
            return mirrored.get() if mirrored is not None else self.values[index]
