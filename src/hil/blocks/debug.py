"""Debug block: debug probes of the station."""

from collections.abc import Mapping
from pathlib import Path

from hil.blocks._lookup import lookup
from hil.resources import ProbeResult
from hil.signals import DebugSignal


class DebugBlock:
    """All debug terminals of a station; without a DUT file the target is passed explicitly."""

    def __init__(
        self,
        signals: Mapping[str, DebugSignal],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.signals = dict(signals)
        self._profile_terminals = profile_terminals

    def __getitem__(self, name: str) -> DebugSignal:
        return lookup(name, self.signals, "debug", self._profile_terminals)

    def flash(self, name: str, image: str | Path, target: str) -> ProbeResult:
        return self[name].flash(image, target)

    def reset(self, name: str, target: str) -> ProbeResult:
        return self[name].reset(target)
