"""Device-independent resources the HAL blocks are built from."""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import serial
from numpy.typing import ArrayLike, NDArray

from hil.config.models import SerialParams


class RelayBank(Protocol):
    """A device with numbered relays that can switch several of them in one operation."""

    name: str

    def set_many(self, states: Mapping[int, bool]) -> None: ...

    def get(self, index: int) -> bool: ...


class InputBank(Protocol):
    """A device with numbered binary inputs."""

    name: str

    def read(self, index: int) -> bool: ...


@dataclass(frozen=True)
class RelayChannel:
    bank: RelayBank
    index: int

    def set(self, on: bool) -> None:
        self.bank.set_many({self.index: on})

    def get(self) -> bool:
        return self.bank.get(self.index)

    def __str__(self) -> str:
        return f"{self.bank.name}.{self.index}"


@dataclass(frozen=True)
class DigitalInput:
    bank: InputBank
    index: int

    def read(self) -> bool:
        return self.bank.read(self.index)

    def __str__(self) -> str:
        return f"{self.bank.name}.{self.index}"


def set_relays(changes: Iterable[tuple[RelayChannel, bool]]) -> None:
    """Apply relay changes with one ``set_many`` call per bank."""
    per_bank: dict[int, tuple[RelayBank, dict[int, bool]]] = {}
    for channel, on in changes:
        _, states = per_bank.setdefault(id(channel.bank), (channel.bank, {}))
        states[channel.index] = on
    for bank, states in per_bank.values():
        bank.set_many(states)


class SerialProvider(Protocol):
    """A device with named serial ports."""

    name: str

    def open_port(
        self, channel: str, params: SerialParams, timeout: float | None
    ) -> serial.Serial: ...


@dataclass(frozen=True)
class SerialLink:
    provider: SerialProvider
    channel: str

    def open(self, params: SerialParams, timeout: float | None = None) -> serial.Serial:
        """Open the port with the DUT's line parameters and the given read timeout."""
        return self.provider.open_port(self.channel, params, timeout)

    def __str__(self) -> str:
        return f"{self.provider.name}.{self.channel}"


def port_settings(params: SerialParams) -> dict[str, Any]:
    """pyserial keyword arguments for the line parameters."""
    return {
        "baudrate": params.baud,
        "bytesize": params.bytesize,
        "parity": params.parity,
        "stopbits": params.stopbits,
    }


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one operation of a debug probe (e.g. one OpenOCD run)."""

    action: str
    output: str
    # exit code of the tool; None when it was stopped (interrupted or timed out)
    returncode: int | None
    duration_s: float
    interrupted: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@runtime_checkable
class DebugProbe(Protocol):
    """A device that flashes and controls the microcontroller of the DUT.

    Failures of the tool are returned in ``ProbeResult``, so that its output can be
    saved; only a missing tool or a closed device raise.
    """

    name: str

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult: ...

    def reset(self, target: str, timeout_s: float) -> ProbeResult: ...

    def halt(self, target: str, timeout_s: float) -> ProbeResult: ...


WaveKind = Literal["dc", "sine", "square", "arbitrary"]


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value}")
    return value


def _periodic(freq: float, amp: float) -> tuple[float, float]:
    freq = _finite("frequency", freq)
    amp = _finite("amplitude", amp)
    if freq <= 0:
        raise ValueError(f"frequency must be positive, got {freq}")
    if amp < 0:
        raise ValueError(f"amplitude must not be negative, got {amp}")
    return freq, amp


@dataclass(frozen=True)
class Waveform:
    """Signal of one generator; voltages in volts, frequencies and rates in hertz.

    ``amplitude`` is the peak value (a sine of amplitude 1 V swings from -1 V to +1 V
    around ``offset``). An arbitrary waveform holds its samples in volts and plays
    them at ``rate`` samples per second, repeated.
    """

    kind: WaveKind
    offset: float = 0.0
    amplitude: float = 0.0
    frequency: float = 0.0
    duty: float = 0.5
    samples: tuple[float, ...] = ()
    rate: float = 0.0

    @classmethod
    def dc(cls, volts: float) -> "Waveform":
        return cls("dc", offset=_finite("voltage", volts))

    @classmethod
    def sine(cls, freq: float, amp: float, offset: float = 0.0) -> "Waveform":
        freq, amp = _periodic(freq, amp)
        return cls("sine", offset=_finite("offset", offset), amplitude=amp, frequency=freq)

    @classmethod
    def square(cls, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5) -> "Waveform":
        freq, amp = _periodic(freq, amp)
        duty = _finite("duty", duty)
        if not 0 < duty < 1:
            raise ValueError(f"duty must be between 0 and 1, got {duty}")
        return cls(
            "square", offset=_finite("offset", offset), amplitude=amp, frequency=freq, duty=duty
        )

    @classmethod
    def arbitrary(cls, samples: ArrayLike, rate: float) -> "Waveform":
        values = tuple(float(v) for v in np.asarray(samples, dtype=np.float64).ravel())
        if not values:
            raise ValueError("an arbitrary waveform needs at least one sample")
        if not all(math.isfinite(v) for v in values):
            raise ValueError("samples of an arbitrary waveform must be finite numbers")
        rate = _finite("rate", rate)
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        return cls("arbitrary", samples=values, rate=rate)

    @property
    def peak_v(self) -> float:
        """Largest absolute voltage of the waveform."""
        if self.kind == "arbitrary":
            return max(abs(v) for v in self.samples)
        return abs(self.offset) + self.amplitude

    def describe(self) -> dict[str, float | int | str]:
        """Parameters for the event log (without the samples)."""
        if self.kind == "dc":
            return {"kind": "dc", "volts": self.offset}
        if self.kind == "arbitrary":
            return {"kind": "arbitrary", "samples": len(self.samples), "rate": self.rate}
        data: dict[str, float | int | str] = {
            "kind": self.kind,
            "freq": self.frequency,
            "amp": self.amplitude,
            "offset": self.offset,
        }
        if self.kind == "square":
            data["duty"] = self.duty
        return data


class AwgDevice(Protocol):
    """A device with numbered waveform generators."""

    name: str

    def awg_apply(self, index: int, wave: Waveform) -> None: ...

    def awg_start(self, index: int) -> None: ...

    def awg_stop(self, index: int) -> None: ...


class ScopeDevice(Protocol):
    """A device with numbered scope channels; samples are in volts."""

    name: str

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]: ...


@dataclass(frozen=True)
class AwgChannel:
    device: AwgDevice
    index: int

    def apply(self, wave: Waveform) -> None:
        """Set the waveform; a running generator changes its output at once."""
        self.device.awg_apply(self.index, wave)

    def sine(self, freq: float, amp: float, offset: float = 0.0) -> None:
        self.apply(Waveform.sine(freq, amp, offset))

    def square(self, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5) -> None:
        self.apply(Waveform.square(freq, amp, offset, duty))

    def dc(self, volts: float) -> None:
        self.apply(Waveform.dc(volts))

    def arbitrary(self, samples: Sequence[float] | NDArray[np.float64], rate: float) -> None:
        self.apply(Waveform.arbitrary(samples, rate))

    def start(self) -> None:
        self.device.awg_start(self.index)

    def stop(self) -> None:
        """Stop the generator; its output goes to 0 V."""
        self.device.awg_stop(self.index)

    def __str__(self) -> str:
        return f"{self.device.name}.awg{self.index + 1}"


@dataclass(frozen=True)
class ScopeChannel:
    device: ScopeDevice
    index: int

    def acquire(self, rate: float, n: int) -> NDArray[np.float64]:
        """``n`` samples taken at ``rate`` samples per second, in volts."""
        return self.device.scope_acquire(self.index, rate, n)

    def __str__(self) -> str:
        return f"{self.device.name}.ch{self.index + 1}"
