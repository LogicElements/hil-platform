"""Analog terminals: generator outputs behind the output multiplexer, scope inputs."""

import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from hil import clock
from hil.errors import ConfigError, ResourceConflict
from hil.recording import Recorder
from hil.resources import AwgChannel, RelayChannel, ScopeChannel, Waveform
from hil.signals.base import Signal
from hil.signals.timing import precise_sleep

log = logging.getLogger("hil.signals.analog")


class _Generator:
    """One generator and the output terminals connected to it."""

    def __init__(self, awg: AwgChannel, mux_position: int | None) -> None:
        self.awg = awg
        # position of the select relay that picks it (0 released, 1 operated);
        # None for a generator wired only to a direct terminal
        self.mux_position = mux_position
        # terminal wired to the generator permanently, without a relay
        self.direct: str | None = None
        self.users: set[str] = set()
        self.wave: Waveform | None = None


def _names(names: set[str]) -> str:
    return ", ".join(sorted(names))


class AnalogRouter:
    """Which generator drives which output terminal; switches the output multiplexer.

    A generator is free when no terminal is connected to it. Terminals connected to
    one generator share its waveform (``follow``). A mux terminal gets a free
    generator without a direct terminal first, so that the fast direct channel stays
    available. Operations of all output terminals are serialized by one lock.
    """

    def __init__(self, generators: Sequence[AwgChannel], recorder: Recorder) -> None:
        if len(generators) not in (0, 2):
            raise ConfigError(f"the output multiplexer needs 2 generators, got {len(generators)}")
        self.recorder = recorder
        self.lock = threading.RLock()
        self._generators = [_Generator(awg, i) for i, awg in enumerate(generators)]

    def add(self, out: "AnalogOut") -> None:
        """Register an output terminal; called by ``AnalogOut``."""
        if out.direct is None:
            if not any(g.mux_position is not None for g in self._generators):
                raise ConfigError(
                    f"terminal {out.name!r} uses the output multiplexer, but the station "
                    "has no 'analog' generators"
                )
            return
        gen = self._find(out.direct)
        if gen is None:
            gen = _Generator(out.direct, None)
            self._generators.append(gen)
        if gen.direct is not None:
            raise ConfigError(
                f"terminals {gen.direct!r} and {out.name!r} are both wired to generator "
                f"{out.direct}"
            )
        gen.direct = out.name

    def _find(self, awg: AwgChannel) -> "_Generator | None":
        return next((g for g in self._generators if g.awg == awg), None)

    def _current(self, name: str) -> "_Generator | None":
        return next((g for g in self._generators if name in g.users), None)

    def generator_of(self, name: str) -> AwgChannel | None:
        with self.lock:
            gen = self._current(name)
            return None if gen is None else gen.awg

    def waveform_of(self, name: str) -> Waveform | None:
        with self.lock:
            gen = self._current(name)
            return None if gen is None else gen.wave

    # --- operations -----------------------------------------------------

    def drive(self, out: "AnalogOut", wave: Waveform) -> None:
        """Put ``wave`` on ``out``; allocate and connect a generator if it has none."""
        with self.lock:
            gen = self._current(out.name)
            if gen is not None:
                gen.awg.apply(wave)
                gen.wave = wave
                self._event(out.name, "waveform", gen, wave)
                return
            gen = self._allocate(out)
            gen.awg.apply(wave)
            gen.awg.start()
            gen.wave = wave
            try:
                self._route(out, gen)
            except BaseException:
                self._stop_unused(gen)
                raise
            gen.users.add(out.name)
            self._event(out.name, "waveform", gen, wave)
            self._note_direct(gen, out.name)

    def follow(self, out: "AnalogOut", other: "AnalogOut") -> None:
        """Connect ``out`` to the generator of ``other``; they share the waveform."""
        with self.lock:
            if other.name == out.name:
                raise ValueError(f"{out.name}: a terminal cannot follow itself")
            gen = self._current(other.name)
            if gen is None:
                raise ResourceConflict(f"{out.name}: {other.name} has no signal to follow")
            current = self._current(out.name)
            if current is gen:
                return
            if out.direct is not None:
                if gen.awg != out.direct:
                    raise ResourceConflict(
                        f"{out.name} is wired directly to {out.direct} and cannot follow "
                        f"{other.name} on {gen.awg}"
                    )
            elif gen.mux_position is None:
                raise ResourceConflict(
                    f"{out.name}: generator {gen.awg} of {other.name} is not on the "
                    "output multiplexer"
                )
            if current is not None:
                self._open_connect(out)
                self._leave(out, current)
            self._route(out, gen)
            gen.users.add(out.name)
            self._event(out.name, "follow", gen, other=other.name)
            self._note_direct(gen, out.name)

    def disconnect(self, out: "AnalogOut") -> None:
        """Disconnect ``out`` from the DUT; stop its generator if nothing else uses it."""
        with self.lock:
            self._open_connect(out)
            gen = self._current(out.name)
            if gen is not None:
                self._leave(out, gen)
            out.recorder.event(out.name, "disconnect")

    def safe_state(self, out: "AnalogOut") -> None:
        """Open both relays of ``out`` and release its generator, even if a relay fails."""
        with self.lock:
            try:
                self._open_connect(out)
                if out.select is not None and out.select.get():
                    out.select.set(False)
            finally:
                gen = self._current(out.name)
                if gen is not None:
                    self._leave(out, gen)

    # --- helpers --------------------------------------------------------

    def _allocate(self, out: "AnalogOut") -> _Generator:
        if out.direct is not None:
            gen = self._find(out.direct)
            if gen is None:
                raise ConfigError(f"terminal {out.name!r} is not registered")
            if gen.users:
                raise ResourceConflict(
                    f"{out.name}: generator {gen.awg} is in use by {_names(gen.users)}"
                )
            return gen
        free = [g for g in self._generators if g.mux_position is not None and not g.users]
        if not free:
            busy = "; ".join(
                f"{g.awg}: {_names(g.users)}"
                for g in self._generators
                if g.mux_position is not None
            )
            raise ResourceConflict(f"{out.name}: both generators are in use ({busy})")
        # keep the generator of the fast direct channel free as long as possible
        free.sort(key=lambda g: g.direct is not None)
        return free[0]

    def _route(self, out: "AnalogOut", gen: _Generator) -> None:
        """Select ``gen`` and connect ``out``; never connects the other generator."""
        if out.select is None or out.connect is None:
            return
        operated = gen.mux_position == 1
        if out.select.get() != operated:
            if out.connect.get():
                out.connect.set(False)
            out.select.set(operated)
        out.connect.set(True)

    def _open_connect(self, out: "AnalogOut") -> None:
        if out.connect is not None and out.connect.get():
            out.connect.set(False)

    def _leave(self, out: "AnalogOut", gen: _Generator) -> None:
        gen.users.discard(out.name)
        if not gen.users:
            gen.wave = None
            gen.awg.stop()

    def _stop_unused(self, gen: _Generator) -> None:
        """After a failed connection: do not leave an unused generator running."""
        if gen.users:
            return
        gen.wave = None
        try:
            gen.awg.stop()
        except Exception as exc:
            log.error("stopping generator %s failed: %s", gen.awg, exc)

    def _note_direct(self, gen: _Generator, user: str) -> None:
        if gen.direct is not None and gen.direct != user:
            self.recorder.event(gen.direct, "shared_generator", generator=str(gen.awg), by=user)

    def _event(
        self, name: str, action: str, gen: _Generator, wave: Waveform | None = None, **data: str
    ) -> None:
        details: dict[str, float | int | str] = {"generator": str(gen.awg), **data}
        if wave is not None:
            details.update(wave.describe())
        self.recorder.event(name, action, **details)


class AnalogOut(Signal):
    """Input of the DUT driven by a generator, directly or through the output multiplexer."""

    kind = "analog_out"

    def __init__(
        self,
        name: str,
        recorder: Recorder,
        router: AnalogRouter,
        direct: AwgChannel | None = None,
        select: RelayChannel | None = None,
        connect: RelayChannel | None = None,
    ) -> None:
        super().__init__(name, recorder)
        if (direct is None) == (select is None or connect is None):
            raise ConfigError(
                f"terminal {name!r} needs either a direct generator, or both select "
                "and connect relays"
            )
        self.router = router
        self.direct = direct
        self.select = select
        self.connect = connect
        router.add(self)

    @property
    def generator(self) -> AwgChannel | None:
        """Generator driving the terminal, None when disconnected."""
        return self.router.generator_of(self.name)

    @property
    def waveform(self) -> Waveform | None:
        return self.router.waveform_of(self.name)

    def sine(self, freq: float, amp: float, offset: float = 0.0) -> None:
        """Sine of peak amplitude ``amp`` volts around ``offset``."""
        self.router.drive(self, Waveform.sine(freq, amp, offset))

    def square(self, freq: float, amp: float, offset: float = 0.0, duty: float = 0.5) -> None:
        self.router.drive(self, Waveform.square(freq, amp, offset, duty))

    def dc(self, volts: float) -> None:
        self.router.drive(self, Waveform.dc(volts))

    def arbitrary(self, samples: Sequence[float] | NDArray[np.float64], rate: float) -> None:
        """Repeat ``samples`` (volts) at ``rate`` samples per second."""
        self.router.drive(self, Waveform.arbitrary(samples, rate))

    def follow(self, other: "AnalogOut") -> None:
        """Connect to the generator of ``other``; a later change of either changes both."""
        self.router.follow(self, other)

    def disconnect(self) -> None:
        self.router.disconnect(self)

    def safe_state(self) -> None:
        self.router.safe_state(self)


# sampling rate of measure(): ten times the 10 kHz bandwidth of HW-ANA-07
DEFAULT_RATE_HZ = 100_000.0


@dataclass(frozen=True)
class Measurement:
    """DC value (mean) and RMS of the AC component of a measured signal, in volts."""

    dc: float
    rms_ac: float


def measurement_of(data: NDArray[np.float64]) -> Measurement:
    if len(data) == 0:
        raise ValueError("no samples to evaluate")
    dc = float(np.mean(data))
    return Measurement(dc, float(np.sqrt(np.mean((data - dc) ** 2))))


class ScopeMux:
    """Terminals sharing one scope channel; one of them is connected and measured at a time.

    Switching opens the ``connect`` relay of the other terminal first, then closes the
    relay of the measured one and waits ``settle_s``. The measured terminal stays
    connected until another terminal needs the channel.
    """

    def __init__(self, scope: ScopeChannel) -> None:
        self.scope = scope
        self.members: list[AnalogIn] = []
        self.active: str | None = None
        self._busy = threading.Lock()

    def add(self, inp: "AnalogIn") -> None:
        members = [*self.members, inp]
        if len(members) > 1 and any(m.connect is None for m in members):
            names = ", ".join(repr(m.name) for m in members)
            raise ConfigError(
                f"terminals {names} share scope channel {self.scope}; each needs a 'connect' relay"
            )
        self.members.append(inp)

    @contextmanager
    def use(self, inp: "AnalogIn") -> Iterator[None]:
        """Connect ``inp`` to the scope channel for one acquisition."""
        if not self._busy.acquire(blocking=False):
            raise ResourceConflict(
                f"{inp.name}: scope channel {self.scope} is busy measuring {self.active}"
            )
        try:
            self.active = inp.name
            connect = inp.connect
            if connect is not None and not connect.get():
                for other in self.members:
                    if other is not inp and other.connect is not None and other.connect.get():
                        other.connect.set(False)
                        other._event("disconnect")
                connect.set(True)
                inp._event("connect")
                precise_sleep(inp.settle_s)
            yield
        finally:
            self.active = None
            self._busy.release()


class AnalogIn(Signal):
    """Output of the DUT measured by a scope channel, optionally through a multiplexer."""

    kind = "analog_in"

    def __init__(
        self,
        name: str,
        recorder: Recorder,
        scope: ScopeChannel,
        mux: ScopeMux,
        connect: RelayChannel | None = None,
        settle_s: float = 0.02,
    ) -> None:
        super().__init__(name, recorder)
        self.scope = scope
        self.mux = mux
        self.connect = connect
        self.settle_s = settle_s
        mux.add(self)

    def _acquire(self, duration_s: float, rate: float) -> NDArray[np.float64]:
        if not duration_s > 0 or not rate > 0:
            raise ValueError(
                f"{self.name}: duration and rate must be positive, got {duration_s} s at {rate} Hz"
            )
        n = max(1, round(duration_s * rate))
        with self.mux.use(self):
            return self.scope.acquire(rate, n)

    def capture(self, duration_s: float, rate: float = DEFAULT_RATE_HZ) -> NDArray[np.float64]:
        """Samples (volts) of ``duration_s`` seconds at ``rate`` samples per second."""
        data = self._acquire(duration_s, rate)
        self._event("capture", samples=len(data), rate=rate)
        return data

    def measure(self, duration_s: float = 0.1, rate: float = DEFAULT_RATE_HZ) -> Measurement:
        """DC value and AC RMS over ``duration_s``; recorded in ``measurements.jsonl``."""
        result = measurement_of(self._acquire(duration_s, rate))
        self.recorder.write(
            "measurements.jsonl",
            {
                "t": round(self.recorder.relative(clock.now()), 6),
                "terminal": self.name,
                "dc": result.dc,
                "rms_ac": result.rms_ac,
                "duration_s": duration_s,
                "rate": rate,
            },
        )
        return result

    def safe_state(self) -> None:
        if self.connect is not None and self.connect.get():
            self.connect.set(False)
            self._event("disconnect")
