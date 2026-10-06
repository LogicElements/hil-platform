"""Station: devices, terminals and blocks built from a station file."""

import atexit
import logging
import signal as os_signal
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType
from typing import Any

import hil.drivers  # noqa: F401  (registers the built-in drivers)
from hil.blocks import CommBlock, DebugBlock, DigitalBlock, FaultMatrix, PowerBlock
from hil.config.loader import LoadedStation, load_station
from hil.config.models import (
    DebugTerminal,
    FaultPathTerminal,
    PowerTerminal,
    Rs485MonitorTerminal,
    Rs485Terminal,
    SenseTerminal,
    SerialTerminal,
    SwitchTerminal,
    terminal_refs,
)
from hil.config.refs import ResourceRef
from hil.drivers.base import Device
from hil.drivers.registry import create_device, open_order
from hil.errors import ConfigError, DeviceError, SignalUnavailable, TerminationRequested
from hil.recording import Recorder
from hil.resources import DebugProbe, DigitalInput, RelayChannel, SerialLink
from hil.signals import (
    DebugSignal,
    FaultPath,
    PowerSignal,
    Rs485Monitor,
    Rs485Signal,
    SenseSignal,
    SerialSignal,
    Signal,
    SwitchSignal,
)

log = logging.getLogger("hil.station")

_Handler = Callable[[int, FrameType | None], Any] | int | None


class Station:
    """A configured HIL station. Constructing it does no I/O; ``open`` connects."""

    def __init__(self, loaded: LoadedStation, recorder: Recorder | None = None) -> None:
        self.config = loaded.config
        self.profile = loaded.profile
        self.source = loaded.source
        self.name = self.config.name
        self.recorder = recorder or Recorder()
        self.devices: dict[str, Device] = {
            name: create_device(name, cfg) for name, cfg in self.config.devices.items()
        }
        self._order = open_order(self.devices)
        for name in self._order:
            try:
                self.devices[name].bind(self.devices)
            except ConfigError as exc:
                raise ConfigError(f"{self.source}: {exc}") from exc
        self.terminals: dict[str, Signal] = {
            name: self._build(name, terminal) for name, terminal in self.config.terminals.items()
        }
        self._terminal_devices: dict[str, frozenset[str]] = {
            name: _devices_of(terminal) for name, terminal in self.config.terminals.items()
        }
        terminals = self.profile.terminals
        self.power = PowerBlock(self._of(PowerSignal), terminals)
        self.digital = DigitalBlock(self._of(SwitchSignal), self._of(SenseSignal), terminals)
        self.faults = FaultMatrix(self._of(FaultPath), terminals)
        self.comm = CommBlock(
            self._of(SerialSignal), self._of(Rs485Signal), self._of(Rs485Monitor), terminals
        )
        self.debug = DebugBlock(self._of(DebugSignal), terminals)
        self._opened: list[str] = []
        self._previous_handlers: dict[int, _Handler] = {}
        self._atexit_registered = False
        self._terminating = False
        self._closing = False

    @classmethod
    def from_files(
        cls,
        station: str | Path,
        profile_dirs: Sequence[Path] = (),
        recorder: Recorder | None = None,
    ) -> "Station":
        return cls(load_station(station, profile_dirs), recorder)

    # --- building -------------------------------------------------------

    def _resource[T](self, terminal: str, ref: ResourceRef, expected: type[T]) -> T:
        try:
            resource = self.devices[ref.device].resource(ref.channel)
        except ConfigError as exc:
            raise ConfigError(f"{self.source}: terminal {terminal!r}: {exc}") from exc
        if not isinstance(resource, expected):
            raise ConfigError(
                f"{self.source}: terminal {terminal!r}: {ref} is not a {expected.__name__}"
            )
        return resource

    def _build(self, name: str, terminal: object) -> Signal:
        rec = self.recorder
        match terminal:
            case PowerTerminal(relays=relays):
                return PowerSignal(
                    name, rec, [self._resource(name, r, RelayChannel) for r in relays]
                )
            case SwitchTerminal(relay=relay):
                return SwitchSignal(name, rec, self._resource(name, relay, RelayChannel))
            case SenseTerminal(input=input_ref):
                return SenseSignal(name, rec, self._resource(name, input_ref, DigitalInput))
            case FaultPathTerminal() as fault:
                short = fault.short
                return FaultPath(
                    name,
                    rec,
                    series=self._resource(name, fault.series, RelayChannel),
                    short=None if short is None else self._resource(name, short, RelayChannel),
                    carries_power=fault.carries_power,
                    allow_short=fault.allow_short,
                )
            case SerialTerminal(port=port):
                return SerialSignal(name, rec, self._resource(name, port, SerialLink))
            case Rs485Terminal(port=port):
                return Rs485Signal(name, rec, self._resource(name, port, SerialLink))
            case Rs485MonitorTerminal(port=port):
                return Rs485Monitor(name, rec, self._resource(name, port, SerialLink))
            case DebugTerminal(probe=probe):
                device = self.devices[probe]
                if not isinstance(device, DebugProbe):
                    raise ConfigError(
                        f"{self.source}: terminal {name!r}: device {probe!r} is not a debug probe"
                    )
                return DebugSignal(name, rec, device)
        kind = getattr(terminal, "kind", "?")
        raise ConfigError(
            f"{self.source}: terminal {name!r}: kind {kind!r} is not supported "
            "by this version of hil"
        )

    def _of[S: Signal](self, cls: type[S]) -> dict[str, S]:
        return {name: s for name, s in self.terminals.items() if isinstance(s, cls)}

    # --- access ---------------------------------------------------------

    def terminal(self, name: str) -> Signal:
        if name not in self.profile.terminals:
            raise ConfigError(
                f"terminal {name!r} is not defined in profile {self.profile.profile!r}"
            )
        signal = self.terminals.get(name)
        if signal is None:
            raise SignalUnavailable(f"terminal {name!r} is not wired on station {self.name!r}")
        return signal

    # --- life cycle -----------------------------------------------------

    def open(self, best_effort: bool = False) -> list[Exception]:
        """Open all devices and set the safe state.

        With ``best_effort`` a device that fails to open, and every device that depends
        on it, is skipped; the safe state is set on the rest and the errors are returned
        instead of raised. ``hil safe`` uses it at boot, so that one missing module does
        not leave the other outputs of the station switched on.
        """
        if best_effort:
            return self._open_best_effort()
        try:
            for name in self._order:
                self.devices[name].open()
                self._opened.append(name)
            self.safe_state()
        except BaseException:
            try:
                self.close()
            except Exception as cleanup_error:
                log.error("cleanup after failed open of station %s: %s", self.name, cleanup_error)
            raise
        return []

    def _open_best_effort(self) -> list[Exception]:
        errors: list[Exception] = []
        failed: set[str] = set()
        for name in self._order:
            device = self.devices[name]
            missing = failed.intersection(device.dependencies())
            if missing:
                failed.add(name)
                errors.append(
                    DeviceError(
                        f"device {name!r} not opened: it depends on {', '.join(sorted(missing))}"
                    )
                )
                continue
            try:
                device.open()
            except Exception as exc:
                log.error("opening device %s failed: %s", name, exc)
                failed.add(name)
                errors.append(exc)
                continue
            self._opened.append(name)
        try:
            self.safe_state()
        except DeviceError as exc:
            errors.append(exc)
        return errors

    def close(self) -> None:
        """Safe state, release signals and devices; signal handlers are restored last."""
        self._closing = True
        try:
            errors: list[Exception] = []
            if self._opened:
                try:
                    self.safe_state()
                except DeviceError as exc:
                    errors.append(exc)
            for signal in self.terminals.values():
                try:
                    signal.close()
                except Exception as exc:
                    log.error("closing terminal %s failed: %s", signal.name, exc)
                    errors.append(exc)
            for name in reversed(self._opened):
                try:
                    self.devices[name].close()
                except Exception as exc:
                    log.error("closing device %s failed: %s", name, exc)
                    errors.append(exc)
            self._opened.clear()
            if errors:
                raise DeviceError(f"closing station {self.name!r} failed: {errors[0]}")
        finally:
            self._remove_emergency_handlers()
            self._closing = False
            self._terminating = False

    def safe_state(self) -> None:
        """Power off first, then every terminal and every open device.

        Terminals on a device that is not open (after ``open(best_effort=True)``) are
        skipped.
        """
        opened = set(self._opened)
        ready = [
            signal
            for name, signal in self.terminals.items()
            if self._terminal_devices[name] <= opened
        ]
        errors: list[Exception] = []
        for signal in ready:
            if isinstance(signal, PowerSignal):
                try:
                    signal.off()
                except Exception as exc:
                    log.error("switching off %s failed: %s", signal.name, exc)
                    errors.append(exc)
        for signal in ready:
            if isinstance(signal, PowerSignal):
                continue
            try:
                signal.safe_state()
            except Exception as exc:
                errors.append(exc)
        for name in self._opened:
            try:
                self.devices[name].safe_state()
            except Exception as exc:
                errors.append(exc)
        if errors:
            details = "; ".join(str(e) for e in errors)
            raise DeviceError(f"station {self.name!r}: safe state failed: {details}")
        self.recorder.event("station", "safe_state")

    def emergency_off(self) -> None:
        for error in self.power.emergency_off():
            log.error("emergency off: %s", error)

    def install_emergency_handlers(self) -> None:
        """Interrupt the main thread on termination signals; power off at interpreter exit.

        The handlers do no device I/O: the main thread may be inside a bus transaction
        and a frame sent from the handler would corrupt it. They raise
        ``TerminationRequested`` and the cleanup (``close``, pytest teardown) sets the
        full safe state.
        """
        if not self._atexit_registered:
            atexit.register(self._at_exit)
            self._atexit_registered = True
        if threading.current_thread() is not threading.main_thread():
            return
        if sys.platform == "win32":
            names: tuple[str, ...] = ("SIGINT", "SIGBREAK")
        else:
            names = ("SIGINT", "SIGTERM", "SIGHUP")
        for signame in names:
            signum = getattr(os_signal, signame)
            if signum in self._previous_handlers:
                continue
            previous = os_signal.getsignal(signum)
            if previous == os_signal.SIG_IGN:
                continue  # e.g. SIGHUP under nohup: the run is meant to survive it
            self._previous_handlers[signum] = previous
            os_signal.signal(signum, self._make_handler(signame, previous))

    def _make_handler(
        self, signame: str, previous: _Handler
    ) -> Callable[[int, FrameType | None], None]:
        def handler(signum: int, frame: FrameType | None) -> None:
            if self._terminating or self._closing:
                log.warning("%s ignored: the station is being put into the safe state", signame)
                return
            self._terminating = True
            log.warning("%s received: stopping, the station goes to the safe state", signame)
            if callable(previous) and previous is not os_signal.default_int_handler:
                previous(signum, frame)
            raise TerminationRequested(signame)

        return handler

    def _remove_emergency_handlers(self) -> None:
        if self._atexit_registered:
            atexit.unregister(self._at_exit)
            self._atexit_registered = False
        if threading.current_thread() is threading.main_thread():
            for signum, previous in self._previous_handlers.items():
                os_signal.signal(signum, previous if previous is not None else os_signal.SIG_DFL)
            self._previous_handlers.clear()

    def _at_exit(self) -> None:
        if self._opened:
            self.emergency_off()

    def __enter__(self) -> "Station":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Station {self.name} ({self.source})>"


def _devices_of(terminal: Any) -> frozenset[str]:
    """Names of the devices a station terminal uses."""
    devices = {ref.device for ref in terminal_refs(terminal)}
    if isinstance(terminal, DebugTerminal):
        devices.add(terminal.probe)
    return frozenset(devices)
