"""Analog block: generator outputs and measured outputs of the DUT."""

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from hil.blocks._lookup import lookup
from hil.signals import DEFAULT_RATE_HZ, AnalogIn, AnalogOut, Measurement


class AnalogBlock:
    """All analog terminals of a station.

    Generator allocation, the output multiplexer and the measuring multiplexers live
    in the terminals (``AnalogRouter``, ``ScopeMux``); the block adds access by name.
    """

    def __init__(
        self,
        outputs: Mapping[str, AnalogOut],
        inputs: Mapping[str, AnalogIn],
        profile_terminals: Mapping[str, str] | None = None,
    ) -> None:
        self.outputs = dict(outputs)
        self.inputs = dict(inputs)
        self._profile_terminals = profile_terminals

    def output(self, name: str) -> AnalogOut:
        return lookup(name, self.outputs, "analog_out", self._profile_terminals)

    def input(self, name: str) -> AnalogIn:
        return lookup(name, self.inputs, "analog_in", self._profile_terminals)

    def sine(self, name: str, freq: float, amp: float, offset: float = 0.0) -> None:
        self.output(name).sine(freq, amp, offset)

    def square(
        self, name: str, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5
    ) -> None:
        self.output(name).square(freq, amp, offset, duty)

    def dc(self, name: str, volts: float) -> None:
        self.output(name).dc(volts)

    def arbitrary(
        self, name: str, samples: Sequence[float] | NDArray[np.float64], rate: float
    ) -> None:
        self.output(name).arbitrary(samples, rate)

    def follow(self, name: str, other: str) -> None:
        self.output(name).follow(self.output(other))

    def disconnect(self, name: str) -> None:
        self.output(name).disconnect()

    def disconnect_all(self) -> None:
        for out in self.outputs.values():
            out.disconnect()

    def measure(
        self, name: str, duration_s: float = 0.1, rate: float = DEFAULT_RATE_HZ
    ) -> Measurement:
        return self.input(name).measure(duration_s, rate)

    def capture(
        self, name: str, duration_s: float, rate: float = DEFAULT_RATE_HZ
    ) -> NDArray[np.float64]:
        return self.input(name).capture(duration_s, rate)
