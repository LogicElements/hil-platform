"""Binary stimulus (switch) and binary response (sense) terminals."""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from hil import clock
from hil.errors import WaitTimeout
from hil.recording import Recorder
from hil.resources import DigitalInput, RelayChannel
from hil.signals.base import Signal
from hil.signals.timing import precise_sleep


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
        started.wait()
        try:
            yield recording
        finally:
            stop.set()
            thread.join()
            self._event(
                "recorded",
                changes=len(recording.changes),
                mean_period_s=round(recording.mean_period_s, 6),
            )
        if errors:
            raise errors[0]
