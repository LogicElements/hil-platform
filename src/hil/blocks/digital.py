"""Digital block: binary stimuli and responses of the DUT."""

from collections.abc import Mapping

from hil.blocks._lookup import lookup
from hil.signals import LogicOutSignal, SenseSignal, SwitchSignal


class DigitalBlock:
    """All switch, sense and logic_out terminals of a station."""

    def __init__(
        self,
        switches: Mapping[str, SwitchSignal],
        senses: Mapping[str, SenseSignal],
        profile_terminals: Mapping[str, str] | None = None,
        logic_outs: Mapping[str, LogicOutSignal] | None = None,
    ) -> None:
        self.switches = dict(switches)
        self.senses = dict(senses)
        self.logic_outs = dict(logic_outs or {})
        self._profile_terminals = profile_terminals

    def switch(self, name: str) -> SwitchSignal:
        return lookup(name, self.switches, "switch", self._profile_terminals)

    def sense(self, name: str) -> SenseSignal:
        return lookup(name, self.senses, "sense", self._profile_terminals)

    def logic_out(self, name: str) -> LogicOutSignal:
        return lookup(name, self.logic_outs, "logic_out", self._profile_terminals)

    def set(self, name: str, on: bool) -> None:
        self.switch(name).set(on)

    def pulse(self, name: str, duration_s: float) -> None:
        self.switch(name).pulse(duration_s)

    def read(self, name: str) -> bool:
        return self.sense(name).read()

    def wait_for(self, name: str, state: bool, timeout: float) -> float:
        return self.sense(name).wait_for(state, timeout)
