"""Binary stimulus (switch, logic_out) and binary response (sense) terminals."""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from hil import clock
from hil.errors import DeviceTimeout, WaitTimeout
from hil.recording import Recorder
from hil.resources import DigitalInput, LogicOutput, RelayChannel
from hil.signals.base import Signal
from hil.signals.timing import precise_sleep

log = logging.getLogger("hil.signals.digital")

# longest wait for the first reading of a recorded input and for the recording to stop
_START_TIMEOUT_S = 5.0
_STOP_TIMEOUT_S = 5.0


class SwitchSignal(Signal):
    """Relay driving a binary input or a button of the DUT."""

    kind = "switch"

    def __init__(self, name: str, recorder: Recorder, relay: RelayChannel) -> None:
        super().__init__(name, recorder)
        self.relay = relay
        self.state = False
        self.last_change: float | None = None

    def set(self, on: bool) -> None:
        self.relay.set(on)
        self.state = on
        self.last_change = clock.now()
        self._event("set", state=on)

    def pulse(self, duration_s: float) -> None:
        """Close the contact for ``duration_s``, e.g. to press a button."""
        self.set(True)
        precise_sleep(duration_s)
        self.set(False)

    def safe_state(self) -> None:
        self.set(False)


class LogicOutSignal(Signal):
    """Logic output of the station driving a 3.3 V logic input of the DUT."""

    kind = "logic_out"

    def __init__(self, name: str, recorder: Recorder, output: LogicOutput) -> None:
        super().__init__(name, recorder)
        self.output = output
        # the driven level, None while released (high impedance)
        self.state: bool | None = None
        self.last_change: float | None = None

    def set(self, value: bool) -> None:
        """Drive the line to logic 1 (True) or 0 (False)."""
        self.output.set(value)
        self.state = value
        self.last_change = clock.now()
        self._event("set", state=value)

    def release(self) -> None:
        """Stop driving the line (high impedance)."""
        self.output.release()
        self.state = None
        self.last_change = clock.now()
        self._event("release")

    def safe_state(self) -> None:
        self.release()


@dataclass
class SenseRecording:
    """Changes of a sense input; the first entry is the state when recording started."""

    changes: list[tuple[float, bool]] = field(default_factory=list)
    samples: int = 0
    duration_s: float = 0.0

    @property
    def mean_period_s(self) -> float:
        return self.duration_s / self.samples if self.samples else 0.0


class SenseSignal(Signal):
    """Binary output of the DUT (dry contact, LED) read by a digital input."""

    kind = "sense"

    def __init__(self, name: str, recorder: Recorder, input: DigitalInput) -> None:
        super().__init__(name, recorder)
        self.input = input

    def read(self) -> bool:
        return self.input.read()

    def wait_for(self, state: bool, timeout: float, poll_s: float = 0.001) -> float:
        """Poll until the input equals ``state``; return the time it was observed."""
        deadline = clock.now() + timeout
        while True:
            value = self.input.read()
            now = clock.now()
            if value == state:
                self._event("observed", state=state)
                return now
            if now >= deadline:
                raise WaitTimeout(f"{self.name}: state {state} not reached within {timeout} s")
            time.sleep(poll_s)

    @contextmanager
    def record(self, period_s: float = 0.001) -> Iterator[SenseRecording]:
        """Record changes in a background thread while the ``with`` block runs."""
        recording = SenseRecording()
        stop = threading.Event()
        started = threading.Event()
        errors: list[Exception] = []

        def run() -> None:
            start = clock.now()
            last: bool | None = None
            try:
                while not stop.is_set():
                    value = self.input.read()
                    now = clock.now()
                    recording.samples += 1
                    if value != last:
                        recording.changes.append((now, value))
                        last = value
                    started.set()
                    stop.wait(period_s)
            except Exception as exc:
                errors.append(exc)
            finally:
                recording.duration_s = clock.now() - start
                started.set()

        thread = threading.Thread(target=run, name=f"hil-record-{self.name}", daemon=True)
        thread.start()
        try:
            ok = started.wait(_START_TIMEOUT_S)
        except BaseException:
            # e.g. TerminationRequested: do not leave the recording thread running
            stop.set()
            raise
        if not ok:
            stop.set()
            raise DeviceTimeout(
                f"{self.name}: first reading of the input took longer than {_START_TIMEOUT_S} s"
            )
        try:
            yield recording
        finally:
            stop.set()
            thread.join(_STOP_TIMEOUT_S)
            if thread.is_alive():
                log.warning("%s: recording did not stop within %s s", self.name, _STOP_TIMEOUT_S)
            self._event(
                "recorded",
                changes=len(recording.changes),
                mean_period_s=round(recording.mean_period_s, 6),
            )
        if errors:
            raise errors[0]
