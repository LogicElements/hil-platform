"""Generic Modbus RTU digital input module (driver ``modbus_di``)."""

from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import Field

from hil.comm.master import ModbusMaster
from hil.drivers.base import Device, DriverConfig
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import DigitalInput


class ModbusDiConfig(DriverConfig):
    bus: str
    address: int = Field(ge=1, le=247)
    count: int = Field(ge=1, le=256)
    # discrete_inputs: function 2, one input per bit; input_registers: function 4,
    # 16 inputs per register starting with its lowest bit
    source: Literal["discrete_inputs", "input_registers"] = "discrete_inputs"
    # Modbus address of the first discrete input or register
    start: int = Field(default=0, ge=0, le=0xFFFF)
    # True: an input reads True when the module reports 0
    invert: bool = False


@register_driver("modbus_di")
class ModbusDi(Device):
    """Inputs of one module; all of them are read with one request."""

    Config = ModbusDiConfig
    config: ModbusDiConfig

    def __init__(self, name: str, config: ModbusDiConfig) -> None:
        super().__init__(name, config)
        self.is_open = False
        self._bus: ModbusRtuBus | None = None
        self._channels = frozenset(str(i) for i in range(config.count))

    def dependencies(self) -> list[str]:
        return [self.config.bus]

    def bind(self, devices: Mapping[str, Device]) -> None:
        self._bus = find_bus(self.name, self.config.bus, devices)

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> DigitalInput:
        if channel not in self._channels:
            self._no_channel(channel)
        return DigitalInput(self, int(channel))

    def _read(self, master: ModbusMaster) -> list[bool]:
        cfg = self.config
        if cfg.source == "discrete_inputs":
            bits = master.read_discrete_inputs(cfg.address, cfg.start, cfg.count)
        else:
            registers = master.read_input_registers(cfg.address, cfg.start, (cfg.count + 15) // 16)
            bits = [bool(registers[i // 16] >> (i % 16) & 1) for i in range(cfg.count)]
        return [bit != cfg.invert for bit in bits]

    def _call(self) -> list[bool]:
        if self._bus is None:
            raise DeviceError(f"device {self.name!r} is not bound to bus {self.config.bus!r}")
        return self._bus.call(self.name, self._read)

    def open(self) -> None:
        try:
            self._call()
        except DeviceTimeout as exc:
            raise DeviceNotFound(
                f"device {self.name!r}: no answer from address {self.config.address} "
                f"on bus {self.config.bus!r}: {exc}"
            ) from exc
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def read_all(self) -> list[bool]:
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        return self._call()

    def read(self, index: int) -> bool:
        return self.read_all()[index]
