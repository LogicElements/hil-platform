"""Fault matrix: cutting and shorting of wires between DUT components."""

from collections.abc import Mapping

from hil.blocks._lookup import lookup
from hil.signals import FaultPath


class FaultMatrix:
    """All fault paths of a station."""

    def __init__(
        self,
        paths: Mapping[str, FaultPath],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.paths = dict(paths)
        self._profile_terminals = profile_terminals

    def __getitem__(self, name: str) -> FaultPath:
        return lookup(name, self.paths, "fault_path", self._profile_terminals)

    def open(self, name: str) -> None:
        self[name].open()

    def short_to_gnd(self, name: str) -> None:
        self[name].short_to_gnd()

    def restore(self, name: str) -> None:
        self[name].restore()

    def restore_all(self) -> None:
        for path in self.paths.values():
            path.restore()
