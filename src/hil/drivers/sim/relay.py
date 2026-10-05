"""Simulated relay module."""

from collections.abc import Collection, Mapping

from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import RelayChannel


class SimRelayConfig(DriverConfig):
    channels: int = Field(default=32, ge=1, le=256)


@register_driver("sim_relay")
class SimRelay(Device):
    """Relay bank keeping its state in memory and logging every operation."""

    Config = SimRelayConfig
    config: SimRelayConfig

    def __init__(self, name: str, config: SimRelayConfig) -> None:
        super().__init__(name, config)
        self.states = [False] * config.channels
        self.history: list[tuple[float, dict[int, bool]]] = []
        self.fail_with: Exception | None = None
        self.is_open = False
        self._channels = frozenset(str(i) for i in range(config.channels))

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> RelayChannel:
        if channel not in self._channels:
            self._no_channel(channel)
        return RelayChannel(self, int(channel))

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def safe_state(self) -> None:
        self.set_many(dict.fromkeys(range(self.config.channels), False))

    def set_many(self, states: Mapping[int, bool]) -> None:
        with self.lock:
            if self.fail_with is not None:
                raise self.fail_with
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            for index in states:
                if not 0 <= index < self.config.channels:
                    raise DeviceError(f"device {self.name!r} has no relay {index}")
            for index, on in states.items():
                self.states[index] = on
            self.history.append((clock.now(), dict(states)))

    def get(self, index: int) -> bool:
        with self.lock:
            return self.states[index]
