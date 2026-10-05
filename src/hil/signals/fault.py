"""Fault path: relays that cut a wire or short it to ground."""

from typing import Literal

from hil.errors import OperationNotAllowed, SignalUnavailable
from hil.recording import Recorder
from hil.resources import RelayChannel, set_relays
from hil.signals.base import Signal

FaultState = Literal["ok", "open", "short"]


class FaultPath(Signal):
    """Wire between DUT components.

    ``series`` is wired through its NC contact (released = wire connected),
    ``short`` connects the wire to ground through its NO contact.
    """

    kind = "fault_path"

    def __init__(
        self,
        name: str,
        recorder: Recorder,
        series: RelayChannel,
        short: RelayChannel | None,
        carries_power: bool = False,
        allow_short: bool = False,
    ) -> None:
        super().__init__(name, recorder)
        self.series = series
        self.short = short
        self.carries_power = carries_power
        self.allow_short = allow_short
        self.state: FaultState = "ok"

    def _apply(self, cut: bool, shorted: bool) -> None:
        changes = [(self.series, cut)]
        if self.short is not None:
            changes.append((self.short, shorted))
        set_relays(changes)

    def open(self) -> None:
        self._apply(cut=True, shorted=False)
        self.state = "open"
        self._event("open")

    def short_to_gnd(self) -> None:
        if self.short is None:
            raise SignalUnavailable(
                f"fault path {self.name!r} has no short-to-ground relay on this station"
            )
        if self.carries_power and not self.allow_short:
            raise OperationNotAllowed(
                f"fault path {self.name!r} carries power; set 'allow_short: true' "
                "in the station file to permit a short to ground"
            )
        self._apply(cut=False, shorted=True)
        self.state = "short"
        self._event("short_to_gnd")

    def restore(self) -> None:
        self._apply(cut=False, shorted=False)
        self.state = "ok"
        self._event("restore")

    def safe_state(self) -> None:
        self.restore()
