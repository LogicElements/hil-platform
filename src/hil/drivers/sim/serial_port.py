"""Simulated serial buses (driver ``sim_serial``)."""

from collections.abc import Collection

import serial
from pydantic import Field, field_validator

from hil.config.models import SerialParams
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.drivers.sim import serial_bus
from hil.errors import DeviceError
from hil.resources import SerialLink, port_settings

if "hil.drivers.sim" not in serial.protocol_handler_packages:
    serial.protocol_handler_packages.append("hil.drivers.sim")


class SimSerialConfig(DriverConfig):
    # bus name -> ports of the bus; what one port writes, all other ports receive
    buses: dict[str, list[str]] = Field(min_length=1)

    @field_validator("buses")
    @classmethod
    def _check_buses(cls, buses: dict[str, list[str]]) -> dict[str, list[str]]:
        seen: set[str] = set()
        for name, ports in buses.items():
            if len(ports) < 2:
                raise ValueError(f"bus {name!r} needs at least two ports")
            for port in ports:
                if not port or "/" in port or "." in port:
                    raise ValueError(f"invalid port name {port!r}")
                if port in seen:
                    raise ValueError(f"port {port!r} is on more than one bus")
                seen.add(port)
        return buses


@register_driver("sim_serial")
class SimSerial(Device):
    """Serial buses in memory; tests play the DUT through ``endpoint``."""

    Config = SimSerialConfig
    config: SimSerialConfig

    def __init__(self, name: str, config: SimSerialConfig) -> None:
        super().__init__(name, config)
        self._channels = frozenset(p for ports in config.buses.values() for p in ports)
        # unique per instance, so two stations with a device of the same name do not clash
        self._key = f"{name}-{id(self):x}"
        self.is_open = False

    def channel_names(self) -> Collection[str]:
        return self._channels

    def resource(self, channel: str) -> SerialLink:
        if channel not in self._channels:
            self._no_channel(channel)
        return SerialLink(self, channel)

    def open(self) -> None:
        try:
            serial_bus.register(self._key, self.config.buses)
        except ValueError as exc:
            raise DeviceError(f"device {self.name!r}: {exc}") from exc
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            serial_bus.unregister(self._key)
            self.is_open = False

    def open_port(self, channel: str, params: SerialParams, timeout: float | None) -> serial.Serial:
        if channel not in self._channels:
            self._no_channel(channel)
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")
        url = f"hilsim://{self._key}/{channel}"
        try:
            return serial.serial_for_url(url, timeout=timeout, **port_settings(params))
        except serial.SerialException as exc:
            raise DeviceError(f"device {self.name!r}: {exc}") from exc

    def endpoint(
        self, channel: str, params: SerialParams | None = None, timeout: float | None = 0.01
    ) -> serial.Serial:
        """Open a port of a simulated bus from a test, e.g. to play the DUT."""
        return self.open_port(channel, params or SerialParams(), timeout)
