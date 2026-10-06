"""Papouch Quido RS 2/32 (driver ``quido_rs_2_32``).

The module must be switched from its default Spinel protocol to Modbus RTU. Relays are
coils 0 to 31 and the two inputs discrete inputs 0 and 1 by default (``coil_base``,
``input_base``). The coil map is verified on hardware, the input map is not yet.
"""

from collections.abc import Collection

from pydantic import Field

from hil.drivers.modbus_relay import ModbusRelayConfig, ModbusRelayModule
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import DigitalInput

INPUTS = ("in0", "in1")


class QuidoConfig(ModbusRelayConfig):
    # Modbus address of the discrete input of input in0
    input_base: int = Field(default=0, ge=0, le=0xFFFF)


@register_driver("quido_rs_2_32")
class QuidoRs232(ModbusRelayModule):
    """32 changeover relays and 2 isolated inputs."""

    Config = QuidoConfig
    config: QuidoConfig

    def channel_names(self) -> Collection[str]:
        return self._relays | frozenset(INPUTS)

    def resource(self, channel: str) -> object:
        if channel in INPUTS:
            return DigitalInput(self, INPUTS.index(channel))
        return super().resource(channel)

    def read(self, index: int) -> bool:
        if not 0 <= index < len(INPUTS):
            raise DeviceError(f"device {self.name!r} has no input {index}")
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        address, start = self.config.address, self.config.input_base + index
        bits = self._bus_or_fail().call(
            self.name, lambda m: m.read_discrete_inputs(address, start, 1)
        )
        return bits[0]
