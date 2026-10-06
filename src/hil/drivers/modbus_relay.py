"""Relay modules on a Modbus RTU bus: common part of the Waveshare and Quido drivers."""

from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import Field

from hil.comm.master import ModbusMaster
from hil.drivers.base import Device, DriverConfig
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import RelayChannel


class ModbusRelayConfig(DriverConfig):
    bus: str
    address: int = Field(ge=1, le=247)
    channels: int = Field(default=32, ge=1, le=256)
    # Modbus address of the coil of relay 0; relay i is coil coil_base + i
    coil_base: int = Field(default=0, ge=0, le=0xFFFF)
    # multiple: one frame per operation (function 15); single: a frame per relay (function 5)
    write: Literal["multiple", "single"] = "multiple"


class ModbusRelayModule(Device):
    """Relays mapped to consecutive coils of one module; the commanded state is kept here.

    One frame of function 15 writes the range from the lowest to the highest changed
    relay; relays in between are written with their commanded state.
    """

    Config = ModbusRelayConfig
    config: ModbusRelayConfig

    def __init__(self, name: str, config: ModbusRelayConfig) -> None:
        super().__init__(name, config)
        self.states = [False] * config.channels
        # coils read when the device was opened (the relay state after power-up)
        self.initial_states: list[bool] | None = None
        self.is_open = False
        self._bus: ModbusRtuBus | None = None
        self._relays = frozenset(str(i) for i in range(config.channels))

    def dependencies(self) -> list[str]:
        return [self.config.bus]

    def bind(self, devices: Mapping[str, Device]) -> None:
        self._bus = find_bus(self.name, self.config.bus, devices)

    def channel_names(self) -> Collection[str]:
        return self._relays

    def resource(self, channel: str) -> object:
        if channel not in self._relays:
            self._no_channel(channel)
        return RelayChannel(self, int(channel))

    def _bus_or_fail(self) -> ModbusRtuBus:
        if self._bus is None:
            raise DeviceError(f"device {self.name!r} is not bound to bus {self.config.bus!r}")
        return self._bus

    def _read_coils(self, master: ModbusMaster) -> list[bool]:
        return master.read_coils(self.config.address, self.config.coil_base, self.config.channels)

    def open(self) -> None:
        bus = self._bus_or_fail()
        try:
            states = bus.call(self.name, self._read_coils)
        except DeviceTimeout as exc:
            raise DeviceNotFound(
                f"device {self.name!r}: no answer from address {self.config.address} "
                f"on bus {self.config.bus!r}: {exc}"
            ) from exc
        with self.lock:
            self.initial_states = list(states)
            self.states = list(states)
            self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def safe_state(self) -> None:
        if self.is_open:
            self.set_many(dict.fromkeys(range(self.config.channels), False))

    def set_many(self, states: Mapping[int, bool]) -> None:
        for index in states:
            if not 0 <= index < self.config.channels:
                raise DeviceError(f"device {self.name!r} has no relay {index}")
        if not states:
            return
        with self.lock:
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            new = list(self.states)
            for index, on in states.items():
                new[index] = on
            address, base = self.config.address, self.config.coil_base
            if self.config.write == "multiple":
                low, high = min(states), max(states)
                values = new[low : high + 1]
                self._bus_or_fail().call(
                    self.name, lambda m: m.write_coils(address, base + low, values)
                )
            else:

                def write_each(master: ModbusMaster) -> None:
                    for index, on in sorted(states.items()):
                        master.write_coil(address, base + index, on)

                self._bus_or_fail().call(self.name, write_each)
            self.states = new

    def get(self, index: int) -> bool:
        with self.lock:
            return self.states[index]

    def read_back(self) -> list[bool]:
        """Coil states as reported by the module (for hardware checks of the coil map)."""
        return self._bus_or_fail().call(self.name, self._read_coils)
