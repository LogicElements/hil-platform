"""Power terminal: DUT supply switched by relays."""

from collections.abc import Sequence

from hil import clock
from hil.errors import OperationNotAllowed
from hil.recording import Recorder
from hil.resources import RelayChannel, set_relays
from hil.signals.base import Signal
from hil.signals.timing import precise_sleep


class PowerSignal(Signal):
    """Supply switched by relays in all poles; relays of one module change in one frame."""

    kind = "power"

    def __init__(self, name: str, recorder: Recorder, relays: Sequence[RelayChannel]) -> None:
        super().__init__(name, recorder)
        if not relays:
            raise ValueError("power terminal needs at least one relay")
        self.relays = tuple(relays)
        self.is_on = False

    def _switch(self, on: bool) -> None:
        set_relays((relay, on) for relay in self.relays)
        self.is_on = on

    def on(self) -> None:
        self._switch(True)
        self._event("on")

    def off(self) -> None:
        self._switch(False)
        self._event("off")

    def outage(self, duration_s: float) -> float:
        """Interrupt the supply for ``duration_s``; return the measured interruption."""
        if duration_s <= 0:
            raise ValueError("outage duration must be positive")
        if not self.is_on:
            raise OperationNotAllowed(f"{self.name}: outage needs the supply switched on")
        self._switch(False)
        t_off = clock.now()
        precise_sleep(duration_s)
        self._switch(True)
        actual = clock.now() - t_off
        self._event("outage", requested_s=duration_s, actual_s=round(actual, 6))
        return actual

    def cycle(self, count: int, on_s: float, off_s: float) -> None:
        """Switch the supply off and on ``count`` times; ends switched on."""
        if count < 1:
            raise ValueError("count must be at least 1")
        if on_s < 0 or off_s < 0:
            raise ValueError("durations must not be negative")
        for _ in range(count):
            self._switch(False)
            precise_sleep(off_s)
            self._switch(True)
            precise_sleep(on_s)
        self._event("cycle", count=count, on_s=on_s, off_s=off_s)

    def safe_state(self) -> None:
        self.off()
