"""Simulated Modbus RTU slave answering in a background thread."""

import logging
import struct
import threading
from dataclasses import dataclass, field
from types import TracebackType

from serial import Serial

from hil import clock
from hil.comm import modbus
from hil.comm.framing import MAX_FRAME, MIN_FRAME, frame_length

log = logging.getLogger("hil.comm.slave")

ILLEGAL_FUNCTION = 1
ILLEGAL_DATA_ADDRESS = 2
ILLEGAL_DATA_VALUE = 3
SERVER_DEVICE_FAILURE = 4

# silence after which an incomplete or unknown request is processed or dropped
_RESYNC_S = 0.05
# longest wait for the echo of a response on a transceiver that hears itself
_ECHO_TIMEOUT_S = 0.5

_KNOWN_FUNCTIONS = frozenset(
    {1, 2, 3, 4, 5, 6, modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS}
)


@dataclass
class ModbusDataStore:
    """Data of a simulated slave; an address missing from a table is an illegal address."""

    coils: dict[int, bool] = field(default_factory=dict)
    discrete_inputs: dict[int, bool] = field(default_factory=dict)
    holding_registers: dict[int, int] = field(default_factory=dict)
    input_registers: dict[int, int] = field(default_factory=dict)


class _ModbusFault(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def request_length(received: bytes) -> int | None:
    """Length of the request at the start of ``received``; None = need more or unknown."""
    if len(received) < 2:
        return None
    function = received[1]
    if function in (1, 2, 3, 4, 5, 6):
        return 8
    if function in (modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS):
        return None if len(received) < 7 else 9 + received[6]
    return None


WAIT = 0
NO_FRAME = -1


def _incomplete_request(tail: bytes) -> bool:
    """True when ``tail`` can still grow into a request whose length is known."""
    if len(tail) < 2 or (
        tail[1] in (modbus.WRITE_MULTIPLE_COILS, modbus.WRITE_MULTIPLE_REGISTERS) and len(tail) < 7
    ):
        return True
    expected = request_length(tail)
    return expected is not None and len(tail) < expected <= MAX_FRAME


def next_frame(buf: bytes, address: int) -> int:
    """Length of the frame at the start of ``buf`` (seen by slave ``address``).

    Returns WAIT when more bytes are needed and NO_FRAME when no valid frame starts here.
    A request for us or a broadcast is framed by its header: a shorter CRC match inside it
    is a coincidence. Other traffic is framed by its CRC (``frame_length``); a 0x00 it ends
    with may instead be the address of a broadcast still arriving, so that case waits.
    """
    if buf[0] in (0, address):
        if _incomplete_request(buf):
            return WAIT
        expected = request_length(buf)
        if expected is not None and expected <= MAX_FRAME and modbus.crc_ok(buf[:expected]):
            return expected
    length = frame_length(buf)
    if length is None:
        return NO_FRAME
    pos = length - 1
    while pos >= MIN_FRAME and buf[pos] == 0:
        if modbus.crc_ok(buf[:pos]) and _incomplete_request(buf[pos:]):
            return WAIT
        pos -= 1
    return length


def _get[V](table: dict[int, V], address: int) -> V:
    if address not in table:
        raise _ModbusFault(ILLEGAL_DATA_ADDRESS)
    return table[address]


def _check_all[V](table: dict[int, V], start: int, count: int) -> None:
    if any(address not in table for address in range(start, start + count)):
        raise _ModbusFault(ILLEGAL_DATA_ADDRESS)


class ModbusSlave:
    """Answers Modbus RTU requests for ``address`` on ``port`` until stopped.

    With ``echo`` the port receives everything it sends (a half-duplex transceiver whose
    receiver stays enabled): the echo of each response is read back and dropped, otherwise
    a write response (equal to its request) would be taken as a new request.
    """

    def __init__(
        self,
        port: Serial,
        address: int,
        store: ModbusDataStore | None = None,
        echo: bool = False,
    ) -> None:
        if not 1 <= address <= 247:
            raise ValueError(f"slave address must be in 1..247, got {address}")
        if getattr(port, "timeout", 1) in (None, 0):
            raise ValueError("the port needs a finite non-zero read timeout")
        self.port = port
        self.address = address
        self.store = store if store is not None else ModbusDataStore()
        self.echo = echo
        # True: requests are received but never answered (a missing device)
        self.silent = False
        self.requests: list[bytes] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        # bytes received before the start (e.g. the echo of earlier raw sends) are stale
        self.port.reset_input_buffer()
        self._thread = threading.Thread(
            target=self._run, name=f"hil-modbus-slave-{self.address}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "ModbusSlave":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def _run(self) -> None:
        received = bytearray()
        last = clock.now()
        while not self._stop.is_set():
            try:
                chunk = self.port.read(max(1, self.port.in_waiting))
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("Modbus slave %s: port failed: %s", self.address, exc)
                return
            now = clock.now()
            if chunk:
                received += chunk
                last = now
            elif received and now - last > _RESYNC_S:
                log.debug("Modbus slave %s: dropping %d stray bytes", self.address, len(received))
                received.clear()
                continue
            self._frame(received)

    def _frame(self, received: bytearray) -> None:
        """Handle every request at the start of ``received``; skip other traffic."""
        while received:
            length = next_frame(bytes(received), self.address)
            if length <= 0:
                if self._skip_to_own_request(received):
                    continue
                if length == NO_FRAME and len(received) >= MAX_FRAME:
                    del received[:1]  # no valid frame can start here
                    continue
                return
            frame = bytes(received[:length])
            del received[:length]
            if request_length(frame) == length or (
                frame[1] not in _KNOWN_FUNCTIONS and frame[1] < 0x80
            ):
                received += self._handle(frame)

    def _skip_to_own_request(self, received: bytearray) -> bool:
        """Drop leading bytes when a complete request for us or a broadcast ends the buffer.

        The master waits after sending a request, so a request it waits for is the last
        thing in the buffer. Only header checks are done per position; the CRC only where
        the request length fits the buffer exactly. An unknown-function request to us has
        no known length (any CRC-valid frame up to the buffer end counts), so it is only
        accepted after leading 0x00 bytes: the lone 0x00 that is left when another slave's
        frame with CRC high byte 0x00 was taken without it. Accepting it after arbitrary
        bytes would answer chance CRC matches inside overheard traffic.
        """
        buf = bytes(received)
        zeros = len(buf) - len(buf.lstrip(b"\0"))
        for start in range(1, len(buf) - 3):
            if buf[start] not in (0, self.address):
                continue
            function = buf[start + 1]
            known_length = request_length(buf[start : start + 7]) == len(buf) - start
            unknown_own = (
                start <= zeros
                and buf[start] == self.address
                and function not in _KNOWN_FUNCTIONS
                and function < 0x80
            )
            if (known_length or unknown_own) and modbus.crc_ok(buf[start:]):
                del received[:start]
                return True
        return False

    def _handle(self, frame: bytes) -> bytes:
        """Answer ``frame``; return bytes read while skipping the echo that are not echo."""
        self.requests.append(frame)
        if frame[0] not in (0, self.address) or self.silent:
            return b""
        response = self.respond(frame)
        if frame[0] == 0:
            return b""
        try:
            self.port.write(response)
            return self._skip_echo(response) if self.echo else b""
        except Exception as exc:
            log.error("Modbus slave %s: write failed: %s", self.address, exc)
            self._stop.set()
            return b""

    def _skip_echo(self, response: bytes) -> bytes:
        """Read back the echo of ``response``; return what was read if it is not the echo.

        Reading exactly the echo right after the write is robust against a repeated
        identical request (which skipping "the next identical frame" would swallow when
        the echo is lost). Bytes that differ from the echo are handed back as traffic.
        """
        echoed = bytearray()
        deadline = clock.now() + _ECHO_TIMEOUT_S
        while len(echoed) < len(response) and clock.now() < deadline:
            echoed += self.port.read(len(response) - len(echoed))
        if echoed == response:
            return b""
        log.warning(
            "Modbus slave %s: echo of the response differs: %s",
            self.address,
            bytes(echoed).hex(" ") or "nothing",
        )
        return bytes(echoed)

    def respond(self, frame: bytes) -> bytes:
        """The response of this slave to the request ``frame`` (CRC already checked)."""
        function = frame[1]
        try:
            body = self._execute(function, frame[2:-2])
        except _ModbusFault as fault:
            return modbus.with_crc(bytes((self.address, function | 0x80, fault.code)))
        except Exception:
            log.exception("Modbus slave %s: request failed internally", self.address)
            return modbus.with_crc(bytes((self.address, function | 0x80, SERVER_DEVICE_FAILURE)))
        return modbus.with_crc(bytes((self.address, function)) + body)

    def _execute(self, function: int, data: bytes) -> bytes:
        store = self.store
        if function in modbus.BIT_READS | modbus.REGISTER_READS:
            if len(data) != 4:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count = struct.unpack(">HH", data)
            if function in modbus.BIT_READS:
                if not 1 <= count <= modbus.MAX_READ_BITS:
                    raise _ModbusFault(ILLEGAL_DATA_VALUE)
                table = store.coils if function == modbus.READ_COILS else store.discrete_inputs
                packed = modbus.pack_bits([_get(table, a) for a in range(start, start + count)])
                return bytes((len(packed),)) + packed
            if not 1 <= count <= modbus.MAX_READ_REGISTERS:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            registers = (
                store.holding_registers
                if function == modbus.READ_HOLDING_REGISTERS
                else store.input_registers
            )
            values = [_get(registers, a) for a in range(start, start + count)]
            return bytes((2 * count,)) + struct.pack(f">{count}H", *values)
        if function in (modbus.WRITE_SINGLE_COIL, modbus.WRITE_SINGLE_REGISTER):
            if len(data) != 4:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            target, value = struct.unpack(">HH", data)
            if function == modbus.WRITE_SINGLE_COIL:
                if value not in (0xFF00, 0):
                    raise _ModbusFault(ILLEGAL_DATA_VALUE)
                _get(store.coils, target)
                store.coils[target] = value == 0xFF00
            else:
                _get(store.holding_registers, target)
                store.holding_registers[target] = value
            return data
        if function == modbus.WRITE_MULTIPLE_COILS:
            if len(data) < 5:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count, size = struct.unpack(">HHB", data[:5])
            if (
                not 1 <= count <= modbus.MAX_WRITE_BITS
                or size != (count + 7) // 8
                or len(data) != 5 + size
            ):
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            _check_all(store.coils, start, count)
            for offset, bit in enumerate(modbus.unpack_bits(data[5:], count)):
                store.coils[start + offset] = bit
            return data[:4]
        if function == modbus.WRITE_MULTIPLE_REGISTERS:
            if len(data) < 5:
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            start, count, size = struct.unpack(">HHB", data[:5])
            if (
                not 1 <= count <= modbus.MAX_WRITE_REGISTERS
                or size != 2 * count
                or len(data) != 5 + size
            ):
                raise _ModbusFault(ILLEGAL_DATA_VALUE)
            _check_all(store.holding_registers, start, count)
            for offset, value in enumerate(struct.unpack(f">{count}H", data[5:])):
                store.holding_registers[start + offset] = value
            return data[:4]
        raise _ModbusFault(ILLEGAL_FUNCTION)
