"""Simulated Analog Discovery 3 (driver ``sim_ad3``)."""

import math
from collections.abc import Collection
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.dio import DIO_CHANNELS, DIO_LINES, DioConfig, Line, dio_resource
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import AwgChannel, ScopeChannel, Waveform

_GENERATORS = {"awg1": 0, "awg2": 1}
_SCOPES = {"ch1": 0, "ch2": 1}


class SimSine(DriverConfig):
    freq: float = Field(gt=0)
    amp: float = Field(ge=0)


class SimScopeInput(DriverConfig):
    """Signal at a scope input: DC level, optional sine and Gaussian noise (sigma in V)."""

    dc: float = 0.0
    sine: SimSine | None = None
    noise: float = Field(default=0.0, ge=0)


class SimAd3Config(DioConfig):
    inputs: dict[Literal["ch1", "ch2"], SimScopeInput] = Field(default_factory=dict)
    # output range of the generators (Analog Discovery 3: ±5 V)
    awg_limit_v: float = Field(default=5.0, gt=0)
    # input range of the scope (Analog Discovery 3: ±25 V); readings are clipped to it
    scope_limit_v: float = Field(default=25.0, gt=0)
    # seed of the noise generator, so that simulated readings are reproducible
    seed: int = 0
    # input line -> output line wired to it inside the device (stimulus/response loopback)
    dio_loop: dict[Line, Line] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_loop(self) -> "SimAd3Config":
        for line, source in self.dio_loop.items():
            if line in self.dio_outputs:
                raise ValueError(f"dio_loop: line {line} is an output")
            if source not in self.dio_outputs:
                raise ValueError(f"dio_loop: line {source} is not an output")
        return self


@register_driver("sim_ad3")
class SimAd3(Device):
    """Two generators and two scope channels held in memory.

    The scope does not see the generators: it reads the inputs from the configuration
    (or from ``set_input``), the DUT between them is not simulated.
    Digital lines: inputs settable from tests (set_dio) or looped to an output (dio_loop).
    """

    Config = SimAd3Config
    config: SimAd3Config

    def __init__(self, name: str, config: SimAd3Config) -> None:
        super().__init__(name, config)
        self.waves: list[Waveform | None] = [None, None]
        self.running = [False, False]
        # (time, generator index, "apply" | "start" | "stop", waveform)
        self.history: list[tuple[float, int, str, Waveform | None]] = []
        # (time, scope index, rate, number of samples)
        self.acquisitions: list[tuple[float, int, float, int]] = []
        self.inputs = [
            config.inputs.get("ch1", SimScopeInput()),
            config.inputs.get("ch2", SimScopeInput()),
        ]
        self.fail_with: Exception | None = None
        self.is_open = False
        # levels of the input lines set from tests
        self.dio_levels = [False] * DIO_LINES
        # driven output lines and their levels; a released line is not present
        self.dio_driven: dict[int, bool] = {}
        # (time, line, level or None when released)
        self.dio_history: list[tuple[float, int, bool | None]] = []
        self._rng = np.random.default_rng(config.seed)

    def channel_names(self) -> Collection[str]:
        return frozenset(_GENERATORS) | frozenset(_SCOPES) | frozenset(DIO_CHANNELS)

    def resource(self, channel: str) -> object:
        if channel in _GENERATORS:
            return AwgChannel(self, _GENERATORS[channel])
        if channel in _SCOPES:
            return ScopeChannel(self, _SCOPES[channel])
        if channel in DIO_CHANNELS:
            return dio_resource(self, self.config, DIO_CHANNELS[channel])
        self._no_channel(channel)

    def open(self) -> None:
        with self.lock:
            self.dio_driven.clear()
            self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def safe_state(self) -> None:
        try:
            for index in range(2):
                self.awg_stop(index)
        finally:
            # outputs are released even when the generators failed to stop
            with self.lock:
                self.dio_driven.clear()

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if not self.is_open:
            raise DeviceError(f"device {self.name!r} is not open")

    def awg_apply(self, index: int, wave: Waveform) -> None:
        with self.lock:
            self._check()
            limit = self.config.awg_limit_v
            if wave.peak_v > limit:
                raise ValueError(
                    f"device {self.name!r}: {wave.peak_v:g} V exceeds the generator "
                    f"range ±{limit:g} V"
                )
            self.waves[index] = wave
            self.history.append((clock.now(), index, "apply", wave))

    def awg_start(self, index: int) -> None:
        with self.lock:
            self._check()
            if self.waves[index] is None:
                raise DeviceError(f"device {self.name!r}: generator {index + 1} has no waveform")
            self.running[index] = True
            self.history.append((clock.now(), index, "start", self.waves[index]))

    def awg_stop(self, index: int) -> None:
        with self.lock:
            self._check()
            self.running[index] = False
            self.waves[index] = None
            self.history.append((clock.now(), index, "stop", None))

    def set_input(
        self,
        channel: str,
        dc: float = 0.0,
        sine: tuple[float, float] | None = None,
        noise: float = 0.0,
    ) -> None:
        """Change the signal at scope input ``channel`` (``ch1`` or ``ch2``)."""
        if channel not in _SCOPES:
            raise ValueError(f"device {self.name!r} has no scope channel {channel!r}")
        signal = SimScopeInput(
            dc=dc,
            sine=None if sine is None else SimSine(freq=sine[0], amp=sine[1]),
            noise=noise,
        )
        with self.lock:
            self.inputs[_SCOPES[channel]] = signal

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]:
        if not rate > 0 or n < 1:
            raise ValueError(f"invalid acquisition: rate {rate}, {n} samples")
        with self.lock:
            self._check()
            signal = self.inputs[index]
            t = np.arange(n, dtype=np.float64) / rate
            data = np.full(n, signal.dc, dtype=np.float64)
            if signal.sine is not None:
                data += signal.sine.amp * np.sin(2 * math.pi * signal.sine.freq * t)
            if signal.noise:
                data += self._rng.normal(0.0, signal.noise, n)
            limit = self.config.scope_limit_v
            self.acquisitions.append((clock.now(), index, rate, n))
            return np.clip(data, -limit, limit)

    # --- digital I/O ----------------------------------------------------

    def set_dio(self, line: int, value: bool) -> None:
        """Set the level driven by the DUT on input ``line``."""
        if not 0 <= line < DIO_LINES:
            raise ValueError(
                f"device {self.name!r}: line {line} is out of range 0..{DIO_LINES - 1}"
            )
        if line in self.config.dio_outputs:
            raise ValueError(f"device {self.name!r}: line {line} is an output")
        with self.lock:
            self.dio_levels[line] = value

    def _level(self, line: int) -> bool:
        if line in self.dio_driven:
            return self.dio_driven[line]
        source = self.config.dio_loop.get(line)
        if source is not None:
            return self.dio_driven.get(source, False)
        return self.dio_levels[line]

    def read(self, index: int) -> bool:
        with self.lock:
            self._check()
            return self._level(index) != (index in self.config.dio_invert)

    def _check_output(self, index: int) -> None:
        if index not in self.config.dio_outputs:
            raise DeviceError(f"device {self.name!r}: line {index} is not an output (dio_outputs)")

    def drive(self, index: int, value: bool) -> None:
        self._check_output(index)
        with self.lock:
            self._check()
            self.dio_driven[index] = value
            self.dio_history.append((clock.now(), index, value))

    def release(self, index: int) -> None:
        self._check_output(index)
        with self.lock:
            self._check()
            self.dio_driven.pop(index, None)
            self.dio_history.append((clock.now(), index, None))
