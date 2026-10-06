"""Shared Modbus RTU bus of relay and input modules (driver ``modbus_rtu_bus``)."""

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Literal

import serial
from pydantic import Field, model_validator

from hil.comm.master import ModbusExceptionResponse, ModbusMaster
from hil.config.models import SerialParams
from hil.config.refs import Ref
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.drivers.serial_ports import (
    FtdiPort,
    ensure_low_latency,
    list_comports_once,
    resolve_port,
)
from hil.errors import ConfigError, DeviceError, DeviceTimeout
from hil.resources import SerialLink, port_settings

log = logging.getLogger("hil.drivers.modbus_bus")

# read timeout of the port; the master bounds the wait for a whole response
_READ_TIMEOUT_S = 0.01
# Quido answers 2 ms after a request at the earliest
_MIN_TURNAROUND_S = 0.002


class ModbusRtuBusConfig(DriverConfig):
    # own port (path, pyserial URL or FTDI chip) or a serial port of another device
    port: str | FtdiPort | None = None
    link: Ref | None = None
    baud: int = Field(default=9600, gt=0)
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    # how long the master waits for a response
    timeout_s: float = Field(default=0.2, gt=0)
    # silence between frames; default 3.5 characters, at least 2 ms
    min_gap_s: float | None = Field(default=None, ge=0)
    # how long an operation waits while another one uses the bus
    lock_timeout_s: float = Field(default=2.0, gt=0)
    # set the FTDI latency timer of an own port to 1 ms (Linux)
    low_latency: bool = True

    @model_validator(mode="after")
    def _one_port(self) -> "ModbusRtuBusConfig":
        if (self.port is None) == (self.link is None):
            raise ValueError("give exactly one of 'port' and 'link'")
        return self

    def params(self) -> SerialParams:
        return SerialParams(baud=self.baud, parity=self.parity, stopbits=self.stopbits)

    def gap_s(self) -> float:
        if self.min_gap_s is not None:
            return self.min_gap_s
        return max(3.5 * self.params().char_time_s(), _MIN_TURNAROUND_S)


@register_driver("modbus_rtu_bus")
class ModbusRtuBus(Device):
    """One RS-485 line with Modbus RTU modules; operations of all modules are serialized."""

    Config = ModbusRtuBusConfig
    config: ModbusRtuBusConfig

    def __init__(self, name: str, config: ModbusRtuBusConfig) -> None:
        super().__init__(name, config)
        self._link: SerialLink | None = None
        self._port: serial.Serial | None = None
        self._master: ModbusMaster | None = None

    def dependencies(self) -> list[str]:
        return [] if self.config.link is None else [self.config.link.device]

    def bind(self, devices: Mapping[str, Device]) -> None:
        ref = self.config.link
        if ref is None:
            return
        resource = devices[ref.device].resource(ref.channel)
        if not isinstance(resource, SerialLink):
            raise ConfigError(f"device {self.name!r}: link {ref} is not a serial port")
        self._link = resource

    @property
    def is_open(self) -> bool:
        return self._master is not None

    def open(self) -> None:
        port = self._open_port(self.config.params())
        self._port = port
        self._master = ModbusMaster(port, self.config.timeout_s, min_gap_s=self.config.gap_s())

    def _open_port(self, params: SerialParams) -> serial.Serial:
        if self.config.link is not None:
            if self._link is None:
                raise DeviceError(f"device {self.name!r}: link {self.config.link} is not bound")
            return self._link.open(params, timeout=_READ_TIMEOUT_S)
        spec = self.config.port
        if spec is None:
            raise ConfigError(f"device {self.name!r}: no port")
        device = resolve_port(self.name, "port", spec, list_comports_once(self.name))
        try:
            port = serial.serial_for_url(device, timeout=_READ_TIMEOUT_S, **port_settings(params))
        except (serial.SerialException, ValueError, OSError) as exc:
            raise DeviceError(f"device {self.name!r}: cannot open port {device}: {exc}") from exc
        if self.config.low_latency:
            ensure_low_latency(device)
        return port

    def close(self) -> None:
        # a stuck operation must not block closing for longer than the lock timeout
        acquired = self.lock.acquire(timeout=self.config.lock_timeout_s)
        try:
            port, self._port, self._master = self._port, None, None
        finally:
            if acquired:
                self.lock.release()
        if port is not None:
            try:
                port.close()
            except Exception as exc:
                log.warning("closing the port of %s failed: %s", self.name, exc)

    @contextmanager
    def session(self) -> Iterator[ModbusMaster]:
        """Exclusive use of the master for one or more exchanges."""
        if not self.lock.acquire(timeout=self.config.lock_timeout_s):
            raise DeviceTimeout(
                f"bus {self.name!r} is busy for more than {self.config.lock_timeout_s} s"
            )
        try:
            if self._master is None:
                raise DeviceError(f"device {self.name!r} is not open")
            yield self._master
        finally:
            self.lock.release()

    def call[T](self, owner: str, action: Callable[[ModbusMaster], T]) -> T:
        """Run ``action`` with the master; a Modbus exception becomes a ``DeviceError``."""
        try:
            with self.session() as master:
                return action(master)
        except ModbusExceptionResponse as exc:
            raise DeviceError(f"device {owner!r}: {exc}") from exc


def find_bus(owner: str, name: str, devices: Mapping[str, Device]) -> ModbusRtuBus:
    """The ``modbus_rtu_bus`` device ``name`` that the module ``owner`` is attached to."""
    bus = devices[name]
    if not isinstance(bus, ModbusRtuBus):
        raise ConfigError(f"device {owner!r}: {name!r} is not a modbus_rtu_bus")
    return bus
