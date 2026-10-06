"""Communication block: serial consoles, RS-485 ports and monitors."""

from collections.abc import Mapping

from hil.blocks._lookup import lookup
from hil.signals import Rs485Monitor, Rs485Signal, SerialSignal


class CommBlock:
    """All communication terminals of a station."""

    def __init__(
        self,
        serials: Mapping[str, SerialSignal],
        rs485s: Mapping[str, Rs485Signal],
        monitors: Mapping[str, Rs485Monitor],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.serials = dict(serials)
        self.rs485s = dict(rs485s)
        self.monitors = dict(monitors)
        self._profile_terminals = profile_terminals

    def serial(self, name: str) -> SerialSignal:
        return lookup(name, self.serials, "serial", self._profile_terminals)

    def rs485(self, name: str) -> Rs485Signal:
        return lookup(name, self.rs485s, "rs485", self._profile_terminals)

    def monitor(self, name: str) -> Rs485Monitor:
        return lookup(name, self.monitors, "rs485_monitor", self._profile_terminals)
