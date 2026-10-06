"""Modbus RTU master over a serial port."""

import logging
import math
import struct
import time
from collections.abc import Callable, Sequence

from serial import Serial, SerialException

from hil import clock
from hil.comm import modbus
from hil.errors import DeviceError, DeviceTimeout, HilError

log = logging.getLogger("hil.comm.master")

EXCEPTION_NAMES = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "server device failure",
    5: "acknowledge",
    6: "server device busy",
}

Exchange = Callable[[bytes, bytes | None], None]


class ModbusExceptionResponse(HilError):
    """The device answered with a Modbus exception."""

    def __init__(self, address: int, function: int, code: int) -> None:
        name = EXCEPTION_NAMES.get(code, "unknown exception")
        super().__init__(
            f"device {address}: function {function} failed with exception {code} ({name})"
        )
        self.address = address
        self.function = function
        self.code = code


def response_length(function: int, received: bytes) -> int | None:
    """Length of the response to ``function`` known from its first bytes; None = need more."""
    if len(received) < 2:
        return None
    if received[1] & 0x80:
        return 5
    if function in modbus.BIT_READS | modbus.REGISTER_READS:
        return None if len(received) < 3 else 5 + received[2]
    return 8


def check_write_response(request: bytes, response: bytes) -> None:
    """A write response repeats the request (functions 5, 6) or its start and count (15, 16)."""
    function = request[1]
    if function in (modbus.WRITE_SINGLE_COIL, modbus.WRITE_SINGLE_REGISTER):
        if response != request:
            raise DeviceError(
                f"device {request[0]}: write response {response.hex(' ')} does not repeat "
                f"the request {request.hex(' ')}"
            )
    elif (
        function in (modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS)
        and response[2:6] != request[2:6]
    ):
        raise DeviceError(
            f"device {request[0]}: write response {response.hex(' ')} does not match "
            f"the start and count of the request {request.hex(' ')}"
        )


class ModbusMaster:
    """Blocking Modbus RTU master.

    The port must have a short read timeout (tens of milliseconds); ``timeout_s`` bounds
    the wait for a whole response. ``min_gap_s`` is the silence kept on the bus between
    the end of one exchange and the next request (3.5 characters by the standard; some
    devices need more time before they listen again).
    """

    def __init__(
        self,
        port: Serial,
        timeout_s: float = 1.0,
        echo: bool = False,
        on_exchange: Exchange | None = None,
        min_gap_s: float = 0.0,
    ) -> None:
        if getattr(port, "timeout", 1) in (None, 0):
            raise ValueError("the port needs a finite non-zero read timeout")
        if min_gap_s < 0:
            raise ValueError("min_gap_s must not be negative")
        self.port = port
        self.timeout_s = timeout_s
        self.echo = echo
        self.on_exchange = on_exchange
        self.min_gap_s = min_gap_s
        self._received = b""
        self._last_traffic = -math.inf

    def _wait_quiet(self) -> None:
        """Keep the bus silent for ``min_gap_s`` after the previous exchange."""
        remaining = self._last_traffic + self.min_gap_s - clock.now()
        if remaining > 0:
            time.sleep(remaining)

    def transact(self, frame: bytes) -> bytes | None:
        """Send ``frame`` and return the validated response (None for a broadcast)."""
        self._received = b""
        self._wait_quiet()
        deadline: float | None = None
        completed = False
        try:
            self.port.reset_input_buffer()
            self.port.write(frame)
            self.port.flush()
            deadline = clock.now() + self.timeout_s
            if self.echo:
                echoed = self._read_exact(len(frame), deadline)
                if echoed != frame:
                    raise DeviceError(f"echo differs from the request: {echoed.hex(' ')}")
            if frame[0] == 0:
                completed = True
                return None
            self._received = b""
            response = self._read_response(frame, deadline)
            completed = True
            check_write_response(frame, response)
            return response
        except SerialException as exc:
            completed = True
            raise DeviceError(f"device {frame[0]}: serial port failed: {exc}") from exc
        except Exception:
            # the master ended the exchange itself (timeout, invalid or exception response)
            completed = True
            raise
        finally:
            now = clock.now()
            if completed or deadline is None:
                self._last_traffic = now
            else:
                # an interrupted exchange (e.g. by a termination signal) may still get its
                # late response; keep the bus quiet until its response window has passed
                self._last_traffic = max(now, deadline)
            if self.on_exchange is not None:
                try:
                    self.on_exchange(frame, self._received or None)
                except Exception:
                    log.exception("on_exchange callback failed")

    def _read_exact(self, count: int, deadline: float) -> bytes:
        received = bytearray()
        while len(received) < count:
            if clock.now() >= deadline:
                raise DeviceTimeout(f"echo of the request not received within {self.timeout_s} s")
            received += self.port.read(count - len(received))
            self._received = bytes(received)
        return bytes(received)

    def _read_response(self, frame: bytes, deadline: float) -> bytes:
        received = bytearray()
        while True:
            need = response_length(frame[1], bytes(received))
            if need is not None and len(received) >= need:
                break
            if clock.now() >= deadline:
                got = bytes(received).hex(" ") or "nothing"
                raise DeviceTimeout(
                    f"device {frame[0]}: no complete response within {self.timeout_s} s "
                    f"(received {got})"
                )
            missing = 1 if need is None else need - len(received)
            received += self.port.read(missing)
            self._received = bytes(received)
        response = bytes(received[:need])
        self._received = response
        if not modbus.crc_ok(response):
            raise DeviceError(f"device {frame[0]}: response with bad CRC: {response.hex(' ')}")
        if response[0] != frame[0]:
            raise DeviceError(
                f"response from device {response[0]} to a request for device {frame[0]}"
            )
        if response[1] == frame[1] | 0x80:
            raise ModbusExceptionResponse(frame[0], frame[1], response[2])
        if response[1] != frame[1]:
            raise DeviceError(
                f"device {frame[0]}: response to function {response[1]}, expected {frame[1]}"
            )
        return response

    def _read(self, frame: bytes) -> bytes:
        if frame[0] == 0:
            raise ValueError("a read request cannot be broadcast")
        response = self.transact(frame)
        if response is None:
            raise DeviceError(f"device {frame[0]}: no response")
        return response

    def _read_registers(self, address: int, function: int, start: int, count: int) -> list[int]:
        response = self._read(modbus.read_request(address, function, start, count))
        if response[2] != 2 * count:
            raise DeviceError(
                f"device {address}: expected {2 * count} data bytes, got {response[2]}"
            )
        return list(struct.unpack(f">{count}H", response[3:-2]))

    def _read_bits(self, address: int, function: int, start: int, count: int) -> list[bool]:
        response = self._read(modbus.read_request(address, function, start, count))
        expected = (count + 7) // 8
        if response[2] != expected:
            raise DeviceError(
                f"device {address}: expected {expected} data bytes, got {response[2]}"
            )
        return modbus.unpack_bits(response[3:-2], count)

    def read_holding_registers(self, address: int, start: int, count: int) -> list[int]:
        return self._read_registers(address, modbus.READ_HOLDING_REGISTERS, start, count)

    def read_input_registers(self, address: int, start: int, count: int) -> list[int]:
        return self._read_registers(address, modbus.READ_INPUT_REGISTERS, start, count)

    def read_coils(self, address: int, start: int, count: int) -> list[bool]:
        return self._read_bits(address, modbus.READ_COILS, start, count)

    def read_discrete_inputs(self, address: int, start: int, count: int) -> list[bool]:
        return self._read_bits(address, modbus.READ_DISCRETE_INPUTS, start, count)

    def write_register(self, address: int, register: int, value: int) -> None:
        self.transact(modbus.write_register_request(address, register, value))

    def write_registers(self, address: int, start: int, values: Sequence[int]) -> None:
        self.transact(modbus.write_registers_request(address, start, values))

    def write_coil(self, address: int, coil: int, on: bool) -> None:
        self.transact(modbus.write_coil_request(address, coil, on))

    def write_coils(self, address: int, start: int, values: Sequence[bool]) -> None:
        self.transact(modbus.write_coils_request(address, start, values))
