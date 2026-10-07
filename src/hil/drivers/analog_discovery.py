"""Digilent Analog Discovery 3 (driver ``analog_discovery_3``) over the WaveForms SDK."""

import threading
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from hil.drivers import dwf
from hil.drivers.base import Device
from hil.drivers.dio import DIO_CHANNELS, DioConfig, dio_resource
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import AwgChannel, ScopeChannel, Waveform

_GENERATORS = {"awg1": 0, "awg2": 1}
_SCOPES = {"ch1": 0, "ch2": 1}

# output range of the generators
AWG_LIMIT_V = 5.0
# scope range, peak to peak (±25 V)
SCOPE_RANGE_V = 50.0
# added to the duration of an acquisition before it is reported as hung
_ACQUIRE_MARGIN_S = 2.0


class AnalogDiscovery3Config(DioConfig):
    # serial number as shown by WaveForms (with or without "SN:"); without it the only
    # connected device is used
    serial: str | None = None
    # path or name of the WaveForms SDK library; default libdwf.so or dwf.dll
    library: str | None = None
    # wait after the scope is configured until its offset settles (Digilent: 2 s)
    scope_warmup_s: float = Field(default=2.0, ge=0)


@register_driver("analog_discovery_3")
class AnalogDiscovery3(Device):
    """Two generators (±5 V), two scope channels (±25 V) and 16 digital lines on one handle."""

    Config = AnalogDiscovery3Config
    config: AnalogDiscovery3Config

    def __init__(self, name: str, config: AnalogDiscovery3Config) -> None:
        super().__init__(name, config)
        self._lib: dwf.DwfLibrary | None = None
        self._handle: int | None = None
        # one lock per instrument: a long scope acquisition does not block the
        # generators or the digital lines (the library serializes single SDK calls)
        self._awg_lock = threading.Lock()
        self._scope_lock = threading.Lock()
        self._dio_lock = threading.Lock()
        # bit masks of the driven levels and of the enabled digital outputs
        self._dio_output = 0
        self._dio_enable = 0

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

    # --- life cycle -----------------------------------------------------

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """All locks of the device, for open, close and safe state."""
        with self.lock, self._awg_lock, self._scope_lock, self._dio_lock:
            yield

    def open(self) -> None:
        # opening an open device reopens it; the previous handle is released first
        self.close()
        lib = dwf.DwfLibrary(self.config.library)
        handle = lib.open(self._find(lib.devices()))
        try:
            lib.scope_setup(handle, SCOPE_RANGE_V)
            lib.dio_reset(handle)
            time.sleep(self.config.scope_warmup_s)
        except BaseException:
            # also on an interrupt during the warm-up, e.g. TerminationRequested
            lib.close(handle)
            raise
        with self._exclusive():
            self._lib, self._handle = lib, handle
            self._dio_output = self._dio_enable = 0

    def _find(self, devices: list[dwf.DwfDeviceInfo]) -> int:
        wanted = self.config.serial
        key = None if wanted is None else wanted.removeprefix("SN:").upper()
        candidates = [d for d in devices if key is None or d.serial.upper() == key]
        connected = ", ".join(f"{d.serial} ({d.name})" for d in devices) or "none"
        if not candidates:
            what = "no WaveForms device" if wanted is None else f"serial {wanted!r} not"
            raise DeviceNotFound(
                f"device {self.name!r}: Analog Discovery with {what} found (connected: {connected})"
            )
        if len(candidates) > 1:
            raise DeviceNotFound(
                f"device {self.name!r}: {len(candidates)} WaveForms devices connected "
                f"({connected}); set 'serial'"
            )
        device = candidates[0]
        if device.in_use:
            raise DeviceNotFound(
                f"device {self.name!r}: {device.serial} is used by another program "
                "(close WaveForms)"
            )
        return device.index

    def close(self) -> None:
        with self._exclusive():
            lib, handle = self._lib, self._handle
            self._lib = self._handle = None
        if lib is not None and handle is not None:
            lib.close(handle)

    def safe_state(self) -> None:
        with self._exclusive():
            if self._lib is None or self._handle is None:
                return
            failed: list[str] = []
            for channel, index in _GENERATORS.items():
                try:
                    self._lib.awg_stop(self._handle, index)
                except DeviceError as exc:
                    failed.append(f"{channel}: {exc}")
            # cleared before the write: a failed write must not let a later drive()
            # re-enable the released lines
            self._dio_output = self._dio_enable = 0
            try:
                self._lib.dio_write(self._handle, 0, 0)
            except DeviceError as exc:
                failed.append(f"dio: {exc}")
        if failed:
            raise DeviceError(f"device {self.name!r}: safe state failed ({'; '.join(failed)})")

    def _opened(self) -> tuple[dwf.DwfLibrary, int]:
        if self._lib is None or self._handle is None:
            raise DeviceError(f"device {self.name!r} is not open")
        return self._lib, self._handle

    # --- generators -----------------------------------------------------

    def awg_apply(self, index: int, wave: Waveform) -> None:
        if wave.peak_v > AWG_LIMIT_V:
            raise ValueError(
                f"device {self.name!r}: {wave.peak_v:g} V exceeds the generator range "
                f"±{AWG_LIMIT_V:g} V"
            )
        with self._awg_lock:
            lib, handle = self._opened()
            if wave.kind == "arbitrary":
                limit = lib.awg_max_samples(handle, index)
                if len(wave.samples) > limit:
                    raise ValueError(
                        f"device {self.name!r}: {len(wave.samples)} samples exceed the "
                        f"generator buffer of {limit}"
                    )
            lib.awg_apply(handle, index, wave)

    def awg_start(self, index: int) -> None:
        with self._awg_lock:
            lib, handle = self._opened()
            lib.awg_start(handle, index)

    def awg_stop(self, index: int) -> None:
        with self._awg_lock:
            lib, handle = self._opened()
            lib.awg_stop(handle, index)

    # --- scope ----------------------------------------------------------

    def scope_acquire(self, index: int, rate: float, n: int) -> NDArray[np.float64]:
        if not rate > 0 or n < 1:
            raise ValueError(f"invalid acquisition: rate {rate}, {n} samples")
        with self._scope_lock:
            lib, handle = self._opened()
            record = n > lib.scope_max_samples(handle)
            return lib.scope_acquire(
                handle, index, rate, n, record, timeout_s=n / rate + _ACQUIRE_MARGIN_S
            )

    # --- digital I/O ----------------------------------------------------

    def read(self, index: int) -> bool:
        with self._dio_lock:
            lib, handle = self._opened()
            level = bool(lib.dio_read(handle) >> index & 1)
        return level != (index in self.config.dio_invert)

    def _check_output(self, index: int) -> None:
        if index not in self.config.dio_outputs:
            raise DeviceError(f"device {self.name!r}: line {index} is not an output (dio_outputs)")

    def drive(self, index: int, value: bool) -> None:
        self._check_output(index)
        bit = 1 << index
        with self._dio_lock:
            lib, handle = self._opened()
            output = self._dio_output | bit if value else self._dio_output & ~bit
            enable = self._dio_enable | bit
            lib.dio_write(handle, output, enable)
            # the state changes only after a successful write
            self._dio_output, self._dio_enable = output, enable

    def release(self, index: int) -> None:
        self._check_output(index)
        bit = 1 << index
        with self._dio_lock:
            lib, handle = self._opened()
            # cleared before the write: a failed release must not let a later drive()
            # re-enable the line
            self._dio_enable &= ~bit
            lib.dio_write(handle, self._dio_output, self._dio_enable)
