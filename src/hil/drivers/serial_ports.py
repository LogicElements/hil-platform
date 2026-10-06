"""Serial ports of the station, e.g. FT4232H channels (driver ``serial_ports``)."""

import logging
import os
import sys
from collections.abc import Callable, Collection, Iterable
from pathlib import Path
from typing import Any

import serial
from pydantic import Field
from serial.tools import list_ports

from hil.config.models import SerialParams
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import SerialLink, port_settings

log = logging.getLogger("hil.drivers.serial_ports")

SYSFS_USB_SERIAL = Path("/sys/bus/usb-serial/devices")


class FtdiPort(DriverConfig):
    """A channel of an FTDI chip found by the chip's serial number."""

    serial: str
    interface: int = Field(default=0, ge=0, le=3)


class SerialPortsConfig(DriverConfig):
    # channel name -> device path, pyserial URL or FTDI serial number and interface
    ports: dict[str, str | FtdiPort] = Field(min_length=1)
    # set the FTDI latency timer to 1 ms (Linux) for passive bus capture
    low_latency: bool = True


def find_ftdi_port(
    serial_number: str, interface: int, ports: Iterable[Any], platform: str = sys.platform
) -> str:
    """Device of channel ``interface`` (0 = A) of the FTDI chip ``serial_number``."""
    letter = "ABCD"[interface]
    for port in ports:
        number = port.serial_number or ""
        if platform == "win32":
            # the FTDI VCP driver reports each channel of a multi-port chip with a suffix
            if number == serial_number + letter:
                return str(port.device)
        elif number == serial_number and (port.location or "").endswith(f":1.{interface}"):
            return str(port.device)
    raise DeviceNotFound(
        f"no FTDI port with serial number {serial_number!r} and interface {interface}"
    )


def ensure_low_latency(
    device: str, sysfs_root: Path = SYSFS_USB_SERIAL, platform: str = sys.platform
) -> None:
    """Set the latency timer of an FTDI port to 1 ms (Linux); warn if it cannot be set."""
    if platform != "linux" or "://" in device:
        return
    tty = Path(os.path.realpath(device)).name
    path = sysfs_root / tty / "latency_timer"
    if not path.exists():
        return
    try:
        if int(path.read_text().strip()) <= 1:
            return
        path.write_text("1")
    except (OSError, ValueError) as exc:
        log.warning(
            "cannot set the latency timer of %s to 1 ms (%s); passive RS-485 capture may "
            "merge frames, set it with an udev rule",
            device,
            exc,
        )


@register_driver("serial_ports")
class SerialPorts(Device):
    Config = SerialPortsConfig
    config: SerialPortsConfig

    def __init__(self, name: str, config: SerialPortsConfig) -> None:
        super().__init__(name, config)
        self._devices: dict[str, str] | None = None

    def channel_names(self) -> Collection[str]:
        return set(self.config.ports)

    def resource(self, channel: str) -> SerialLink:
        if channel not in self.config.ports:
            self._no_channel(channel)
        return SerialLink(self, channel)

    def open(self) -> None:
        """Resolve the device of every channel and check that it exists (ports stay closed)."""
        available: list[Any] | None = None

        def comports() -> list[Any]:
            nonlocal available
            if available is None:
                try:
                    available = list(list_ports.comports())
                except OSError as exc:
                    raise DeviceError(
                        f"device {self.name!r}: cannot list serial ports: {exc}"
                    ) from exc
            return available

        devices: dict[str, str] = {}
        for channel, spec in self.config.ports.items():
            if isinstance(spec, FtdiPort):
                devices[channel] = find_ftdi_port(
                    spec.serial, spec.interface, comports(), platform=sys.platform
                )
                continue
            if "://" not in spec and not self._port_exists(spec, comports):
                raise DeviceNotFound(
                    f"device {self.name!r}: serial port {channel!r} not found: {spec}"
                )
            devices[channel] = spec
        if self.config.low_latency and sys.platform == "win32":
            log.info(
                "%s: the FTDI latency timer cannot be checked on Windows; set it to 1 ms "
                "in Device Manager",
                self.name,
            )
        self._devices = devices

    @staticmethod
    def _port_exists(path: str, comports: Callable[[], list[Any]]) -> bool:
        if sys.platform != "win32":
            return os.path.exists(path)
        name = path.removeprefix("\\\\.\\").upper()  # \\.\COM10 names the port COM10
        return any(str(port.device).upper() == name for port in comports())

    def close(self) -> None:
        self._devices = None

    def open_port(self, channel: str, params: SerialParams, timeout: float | None) -> serial.Serial:
        if channel not in self.config.ports:
            self._no_channel(channel)
        if self._devices is None:
            raise DeviceError(f"device {self.name!r} is not open")
        device = self._devices[channel]
        try:
            port = serial.serial_for_url(device, timeout=timeout, **port_settings(params))
        except (serial.SerialException, ValueError, OSError) as exc:
            raise DeviceError(
                f"device {self.name!r}: cannot open port {channel!r} ({device}): {exc}"
            ) from exc
        if self.config.low_latency:
            ensure_low_latency(device)
        return port
