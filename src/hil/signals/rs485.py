"""RS-485 terminals: active port (``rs485``) and passive monitor (``rs485_monitor``)."""

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from serial import Serial, SerialException

from hil import clock
from hil.comm.faults import FaultKind, corrupt_crc, extend, truncate, wrong_parity
from hil.comm.framing import Frame, FrameSplitter
from hil.comm.master import ModbusMaster
from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.errors import DeviceError, OperationNotAllowed, ResourceConflict, WaitTimeout
from hil.recording import Recorder
from hil.resources import SerialLink
from hil.signals.port import PortSignal


class Rs485Signal(PortSignal):
    """Active RS-485 port of the platform: Modbus master or slave, raw and faulty frames."""

    kind = "rs485"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self._slave: ModbusSlave | None = None

    def _check_no_slave(self, what: str) -> None:
        if self._slave is not None:
            raise ResourceConflict(
                f"{self.alias}: {what} is not possible while the platform acts as "
                f"Modbus slave {self._slave.address}"
            )

    @property
    def modbus(self) -> ModbusMaster:
        """Modbus RTU master on this port."""
        self._check_no_slave("the Modbus master")
        return ModbusMaster(
            self.port, self.params.timeout_s, echo=self.params.echo, on_exchange=self._exchange
        )

    def _exchange(self, request: bytes, response: bytes | None) -> None:
        self._event(
            "modbus",
            request=request.hex(" "),
            response=None if response is None else response.hex(" "),
        )

    @contextmanager
    def slave(self, address: int, store: ModbusDataStore | None = None) -> Iterator[ModbusSlave]:
        """Act as Modbus slave ``address`` while the ``with`` block runs."""
        self._check_no_slave("another slave")
        slave = ModbusSlave(self.port, address, store, echo=self.params.echo)
        slave.start()
        try:
            self._slave = slave
            self._event("slave_start", address=address)
            yield slave
        finally:
            self._stop_slave()

    def _stop_slave(self) -> None:
        slave, self._slave = self._slave, None
        if slave is not None:
            slave.stop()
            self._event("slave_stop", address=slave.address)

    def _port_failed(self, exc: SerialException) -> DeviceError:
        return DeviceError(f"{self.alias}: serial port failed: {exc}")

    def _send(self, data: bytes) -> None:
        port = self.port
        try:
            port.write(data)
            port.flush()
        except SerialException as exc:
            raise self._port_failed(exc) from exc

    def send_raw(self, data: bytes) -> None:
        self._check_no_slave("sending")
        payload = bytes(data)
        self._send(payload)
        self._event("send_raw", data=payload.hex(" "))

    def inject(self, kind: FaultKind, frame: bytes) -> bytes:
        """Send ``frame`` damaged by ``kind``; return the bytes sent."""
        self._check_no_slave("fault injection")
        if kind == "bad_crc":
            payload = corrupt_crc(frame)
        elif kind == "truncated":
            payload = truncate(frame)
        elif kind == "extended":
            payload = extend(frame)
        elif kind == "bad_parity":
            payload = bytes(frame)
        else:
            raise ValueError(f"unknown fault kind {kind!r}")
        if kind == "bad_parity":
            port = self.port
            original = port.parity
            port.parity = wrong_parity(original)
            try:
                self._send(payload)
                # flush() on Windows returns before the chip FIFO is empty; restoring the
                # parity earlier would send the tail with the right parity
                # (verify on hardware in plan 3)
                time.sleep(len(payload) * self.params.char_time_s() + 0.002)
            finally:
                port.parity = original
        else:
            self._send(payload)
        self._event("inject", kind=kind, data=payload.hex(" "))
        return payload

    def flood(self, duration_s: float, chunk: int = 64, seed: int | None = None) -> int:
        """Send random bytes at line rate for ``duration_s``; return the number of bytes."""
        self._check_no_slave("flooding")
        if duration_s <= 0 or chunk < 1:
            raise ValueError("duration and chunk size must be positive")
        rng = random.Random(seed)
        port = self.port
        char_s = self.params.char_time_s()
        start = clock.now()
        sent = 0
        try:
            while (now := clock.now()) - start < duration_s:
                ahead = start + sent * char_s - now
                if ahead > 0:
                    time.sleep(ahead)
                    continue
                port.write(rng.randbytes(chunk))
                sent += chunk
            port.flush()
        except SerialException as exc:
            raise self._port_failed(exc) from exc
        self._event("flood", duration_s=duration_s, bytes=sent)
        return sent

    def safe_state(self) -> None:
        self._stop_slave()

    def _on_close(self) -> None:
        self._stop_slave()


class Rs485Monitor(PortSignal):
    """Passive RS-485 capture with Modbus RTU decoding."""

    kind = "rs485_monitor"

    def __init__(self, name: str, recorder: Recorder, link: SerialLink) -> None:
        super().__init__(name, recorder, link)
        self.frames: list[Frame] = []
        self._cond = threading.Condition()
        self._cursor = 0
        self._started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            return
        port = self.port
        port.reset_input_buffer()
        splitter = FrameSplitter(self.params.gap_s())
        self._stop.clear()
        self._error = None
        self._started = True
        self._thread = threading.Thread(
            target=self._run, args=(port, splitter), name=f"hil-monitor-{self.name}", daemon=True
        )
        self._thread.start()
        self._event("monitor_start", gap_s=splitter.gap_s)

    def stop(self) -> list[Frame]:
        thread, self._thread = self._thread, None
        if thread is not None:
            self._stop.set()
            thread.join(timeout=1.0)
            self._event("monitor_stop", frames=len(self.frames))
        with self._cond:
            return list(self.frames)

    def _run(self, port: Serial, splitter: FrameSplitter) -> None:
        try:
            while not self._stop.is_set():
                data = port.read(max(1, port.in_waiting))
                now = clock.now()
                self._add(splitter.feed(data, now) if data else splitter.poll(now))
        except Exception as exc:
            if not self._stop.is_set():
                self._error = exc
                self._event("port_failed", error=str(exc))
        finally:
            self._add(splitter.flush())
            with self._cond:
                self._cond.notify_all()

    def _add(self, frames: list[Frame]) -> None:
        if not frames:
            return
        for frame in frames:
            record = frame.to_record(self.recorder.relative(frame.t))
            self.recorder.write(f"rs485-{self.alias}.jsonl", record)
        with self._cond:
            self.frames.extend(frames)
            self._cond.notify_all()

    def wait_for_frame(self, predicate: Callable[[Frame], bool], timeout: float) -> Frame:
        """Wait for a matching frame after the one returned by the previous call."""
        if not self._started:
            raise OperationNotAllowed(f"{self.alias}: start() the monitor first")
        deadline = clock.now() + timeout
        with self._cond:
            while True:
                while self._cursor < len(self.frames):
                    frame = self.frames[self._cursor]
                    self._cursor += 1
                    if predicate(frame):
                        return frame
                if self._error is not None:
                    raise DeviceError(
                        f"{self.alias}: monitor port failed: {self._error}"
                    ) from self._error
                if not self.running:
                    raise WaitTimeout(
                        f"{self.alias}: monitor is stopped; no matching frame among "
                        f"{len(self.frames)} captured"
                    )
                remaining = deadline - clock.now()
                if remaining <= 0:
                    raise WaitTimeout(
                        f"{self.alias}: no matching frame within {timeout} s "
                        f"({len(self.frames)} frames captured)"
                    )
                self._cond.wait(remaining)

    def safe_state(self) -> None:
        self.stop()
        with self._cond:
            self.frames.clear()
            self._cursor = 0
        self._started = False

    def _on_close(self) -> None:
        self.stop()
