"""DUT: logical signal names mapped to station terminals."""

from typing import Any

from hil.config.models import DutConfig
from hil.errors import SignalUnavailable
from hil.signals import Signal
from hil.station import Station


class Dut:
    """Signals of the DUT, accessible as attributes (``dut.door_sensor``)."""

    def __init__(self, config: DutConfig, station: Station) -> None:
        self.config = config
        self.station = station
        self.name = config.dut

    def signal(self, name: str) -> Signal:
        spec = self.config.signals.get(name)
        if spec is None:
            known = ", ".join(sorted(self.config.signals))
            raise AttributeError(f"DUT {self.name!r} has no signal {name!r} (known: {known})")
        try:
            return self.station.terminal(spec.terminal)
        except SignalUnavailable as exc:
            raise SignalUnavailable(f"signal {name!r}: {exc}") from exc

    def params(self, name: str) -> dict[str, Any]:
        if name not in self.config.signals:
            raise AttributeError(f"DUT {self.name!r} has no signal {name!r}")
        return self.config.signals[name].params()

    def available(self, name: str) -> bool:
        try:
            self.signal(name)
        except SignalUnavailable:
            return False
        return True

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.signal(name)

    def __repr__(self) -> str:
        return f"<Dut {self.name} on {self.station.name}>"
