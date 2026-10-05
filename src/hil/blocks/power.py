"""Power block: switching of the DUT supply."""

import logging
from collections.abc import Mapping

from hil.blocks._lookup import lookup
from hil.signals import PowerSignal

log = logging.getLogger("hil.blocks.power")


class PowerBlock:
    """All power terminals of a station."""

    def __init__(
        self,
        signals: Mapping[str, PowerSignal],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.signals = dict(signals)
        self._profile_terminals = profile_terminals

    def __getitem__(self, name: str) -> PowerSignal:
        return lookup(name, self.signals, "power", self._profile_terminals)

    def on(self, name: str) -> None:
        self[name].on()

    def off(self, name: str) -> None:
        self[name].off()

    def emergency_off(self) -> list[Exception]:
        """Switch every power terminal off; never raises, returns the errors."""
        errors: list[Exception] = []
        for signal in self.signals.values():
            try:
                signal.off()
            except Exception as exc:
                log.error("emergency off of %s failed: %s", signal.name, exc)
                errors.append(exc)
        return errors
