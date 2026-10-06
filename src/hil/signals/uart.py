"""Serial console or log of the DUT (terminal kind ``serial``)."""

import logging
import re
import threading

from serial import Serial, SerialException

from hil import clock
from hil.errors import DeviceError, WaitTimeout
from hil.recording import Recorder
from hil.resources import SerialLink
from hil.signals.port import PortSignal

log = logging.getLogger("hil.signals.uart")

_TAIL = 200


class SerialSignal(PortSignal):
    """Received bytes are logged line by line and kept for ``expect`` and ``read_until``."""

    kind = "serial"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self._cond = threading.Condition()
        self._buffer = bytearray()
        self._pos = 0
        self._generation = 0
        self._line = bytearray()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    def _on_open(self, port: Serial) -> None:
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._read_loop, args=(port,), name=f"hil-serial-{self.name}", daemon=True
        )
        self._thread.start()

    def _on_close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._line:
            text = bytes(self._line).rstrip(b"\r").decode("utf-8", errors="replace")
            self._line.clear()
            self.recorder.write_line(f"serial-{self.alias}.log", text)

    def _read_loop(self, port: Serial) -> None:
        try:
            while not self._stop.is_set():
                generation = self._generation
                data = port.read(max(1, port.in_waiting))
                if data:
                    self._received(data, generation)
        except Exception as exc:
            if not self._stop.is_set():
                log.error("serial port %s failed: %s", self.alias, exc)
                self._error = exc
                self._event("port_failed", error=str(exc))
        finally:
            with self._cond:
                self._cond.notify_all()

    def _received(self, data: bytes, generation: int) -> None:
        # log complete lines first, so a caller woken by ``expect`` finds them in the file
        self._line.extend(data)
        while (end := self._line.find(b"\n")) >= 0:
            line = bytes(self._line[:end]).rstrip(b"\r")
            del self._line[: end + 1]
            text = line.decode("utf-8", errors="replace")
            self.recorder.write_line(f"serial-{self.alias}.log", text)
        with self._cond:
            if generation == self._generation:
                self._buffer.extend(data)
            self._cond.notify_all()

    def _check_reader(self) -> None:
        if self._error is not None:
            raise DeviceError(f"{self.alias}: serial port failed: {self._error}") from self._error

    def _tail(self) -> bytes:
        return bytes(self._buffer[self._pos :][-_TAIL:])

    def write(self, data: bytes | str) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        port = self.port
        self._check_reader()
        try:
            port.write(payload)
        except SerialException as exc:
            raise DeviceError(f"{self.alias}: serial port failed: {exc}") from exc
        self._event("write", data=payload.decode("utf-8", errors="replace"))

    def expect(self, pattern: str | bytes, timeout: float) -> re.Match[bytes]:
        """Wait for ``pattern`` (a regular expression) in output not consumed yet."""
        regex = re.compile(pattern.encode("utf-8") if isinstance(pattern, str) else pattern)
        _ = self.port
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                match = regex.search(bytes(self._buffer[self._pos :]))
                if match is not None:
                    self._pos += match.end()
                    break
                self._check_reader()
                remaining = deadline - clock.now()
                if remaining <= 0:
                    raise WaitTimeout(
                        f"{self.alias}: {pattern!r} not received within {timeout} s; "
                        f"last output: {self._tail()!r}"
                    )
                self._cond.wait(remaining)
        self._event("expect", pattern=regex.pattern.decode("utf-8", errors="replace"))
        return match

    def read_until(self, terminator: bytes = b"\n", timeout: float = 1.0) -> bytes:
        """Consume output up to and including ``terminator``."""
        _ = self.port
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                end = self._buffer.find(terminator, self._pos)
                if end >= 0:
                    stop = end + len(terminator)
                    data = bytes(self._buffer[self._pos : stop])
                    self._pos = stop
                    return data
                self._check_reader()
                remaining = deadline - clock.now()
                if remaining <= 0:
                    raise WaitTimeout(
                        f"{self.alias}: {terminator!r} not received within {timeout} s; "
                        f"last output: {self._tail()!r}"
                    )
                self._cond.wait(remaining)

    def safe_state(self) -> None:
        """Forget the output received so far, so the next test does not match it."""
        if self._line:
            text = bytes(self._line).rstrip(b"\r").decode("utf-8", errors="replace")
            self._line.clear()
            self.recorder.write_line(f"serial-{self.alias}.log", text)
        with self._cond:
            self._generation += 1
            self._buffer.clear()
            self._pos = 0
        port = self._port
        if port is not None:
            try:
                port.reset_input_buffer()
            except Exception as exc:
                log.warning("serial port %s: cannot reset input buffer: %s", self.alias, exc)
        if self._error is not None:
            # the reader stopped on a port failure; reopen the port on next use
            log.info("serial port %s failed earlier, closing it", self.alias)
            try:
                self.close()
            except Exception as exc:
                log.warning("serial port %s: closing failed: %s", self.alias, exc)
