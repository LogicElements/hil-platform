"""pyserial URL handler ``hilsim://<registry key>/<port>`` for simulated serial ports.

pyserial finds this module because the ``sim_serial`` driver adds ``hil.drivers.sim``
to ``serial.protocol_handler_packages``.
"""

import threading
from collections.abc import Buffer
from typing import Any
from urllib.parse import urlsplit

from serial.serialutil import PortNotOpenError, SerialBase, SerialException

from hil import clock
from hil.drivers.sim import serial_bus


def parse_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    key, port = parts.netloc, parts.path.lstrip("/")
    if parts.scheme != "hilsim" or not key or not port:
        raise SerialException(f"expected 'hilsim://<key>/<port>', got {url!r}")
    return key, port


class Serial(SerialBase):
    """A port of a simulated bus (see ``hil.drivers.sim.serial_bus``)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._cond = threading.Condition()
        self._rx = bytearray()
        self._bus: serial_bus.SimBus | None = None
        # received writes whose line settings differ from ours; a real UART would
        # report parity or framing errors
        self.line_errors = 0
        super().__init__(*args, **kwargs)

    def open(self) -> None:
        if self.portstr is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")
        key, port = parse_url(self.portstr)
        self._bus = serial_bus.attach(key, port, self)
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            self.is_open = False
            bus, self._bus = self._bus, None
            if bus is not None:
                bus.detach(self)
            with self._cond:
                self._cond.notify_all()
        super().close()

    def _reconfigure_port(self, *args: Any) -> None:
        """Line settings are compared with the sender's on every delivery."""

    def from_url(self, url: str) -> None:
        parse_url(url)

    def line_settings(self) -> serial_bus.LineSettings:
        return (self.baudrate, self.bytesize, self.parity, self.stopbits)

    def receive(self, data: bytes, settings: serial_bus.LineSettings) -> None:
        with self._cond:
            if settings != self.line_settings():
                self.line_errors += 1
            self._rx.extend(data)
            self._cond.notify_all()

    def bus_closed(self) -> None:
        with self._cond:
            self._bus = None
            self._cond.notify_all()

    @property
    def in_waiting(self) -> int:
        with self._cond:
            return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise PortNotOpenError()
        deadline = None if self.timeout is None else clock.now() + self.timeout
        with self._cond:
            while len(self._rx) < size:
                if not self.is_open:
                    raise PortNotOpenError()
                if self._bus is None:
                    if self._rx:
                        break
                    raise SerialException("simulated serial device was closed")
                remaining = None if deadline is None else deadline - clock.now()
                if remaining is not None and remaining <= 0:
                    break
                self._cond.wait(remaining)
            data = bytes(self._rx[:size])
            del self._rx[:size]
        return data

    def write(self, data: Buffer, /) -> int:
        if not self.is_open:
            raise PortNotOpenError()
        payload = bytes(data)
        bus = self._bus
        if bus is None:
            raise SerialException("simulated serial device was closed")
        bus.deliver(self, payload)
        return len(payload)

    def reset_input_buffer(self) -> None:
        with self._cond:
            self._rx.clear()

    def reset_output_buffer(self) -> None:
        """Nothing is buffered on output."""

    @property
    def out_waiting(self) -> int:
        return 0

    def cancel_read(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _update_break_state(self) -> None:
        """Break is not simulated."""

    def _update_rts_state(self) -> None:
        """Modem lines are not simulated."""

    def _update_dtr_state(self) -> None:
        """Modem lines are not simulated."""

    @property
    def cts(self) -> bool:
        return False

    @property
    def dsr(self) -> bool:
        return False

    @property
    def ri(self) -> bool:
        return False

    @property
    def cd(self) -> bool:
        return False
