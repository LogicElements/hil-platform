"""Device-independent resources the HAL blocks are built from."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import serial

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
