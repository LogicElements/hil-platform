"""Thin ctypes layer over the WaveForms SDK library (libdwf.so, dwf.dll).

Only the functions the ``analog_discovery_3`` driver needs, wrapped in Python
methods. The library is loaded when ``DwfLibrary`` is created, i.e. in ``open()``
of the driver, so that stations without an Analog Discovery do not need it.

AutoConfigure is turned off when a device is opened. With it on (the SDK default)
every ``...Set`` call reconfigures the device at once, so a waveform change on a
running generator would reach the DUT parameter by parameter (e.g. the new amplitude
around the old offset) and a stopped generator would put each intermediate offset
on its idle output. With it off, settings take effect only on
``FDwfAnalogOutConfigure`` / ``FDwfAnalogInConfigure``, i.e. all at once.
"""

import ctypes
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from hil import clock
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import Waveform

# constants of dwf.h
ENUM_ALL = 0
NODE_CARRIER = 0
FUNC_DC = 0
FUNC_SINE = 1
FUNC_SQUARE = 2
FUNC_CUSTOM = 30
PARAM_ON_CLOSE = 4
ON_CLOSE_SHUTDOWN = 2
IDLE_OFFSET = 1
ACQ_SINGLE = 0
ACQ_RECORD = 3
STATE_DONE = 2
# fStart of FDwfAnalogOutConfigure
AWG_STOP = 0
AWG_START = 1
AWG_APPLY = 3  # apply the settings without changing the running state

_FUNCTIONS = {"dc": FUNC_DC, "sine": FUNC_SINE, "square": FUNC_SQUARE, "arbitrary": FUNC_CUSTOM}
_POLL_S = 0.001

_log = logging.getLogger("hil.drivers.dwf")

# loader of the shared library; the tests replace it with a fake library
_load: Callable[[str], Any] = ctypes.CDLL


def default_library() -> str:
    return "dwf.dll" if sys.platform == "win32" else "libdwf.so"


@dataclass(frozen=True)
class NodeSettings:
    """Settings of the carrier node of one generator."""

    function: int
    frequency: float
    amplitude: float
    offset: float
    # duty cycle in percent
    symmetry: float
    # samples of a custom function, normalized to -1..1
    data: tuple[float, ...] | None = None


def node_settings(wave: Waveform) -> NodeSettings:
    if wave.kind == "dc":
        return NodeSettings(FUNC_DC, 0.0, 0.0, wave.offset, 50.0)
    if wave.kind == "arbitrary":
        low, high = min(wave.samples), max(wave.samples)
        offset = (high + low) / 2
        amplitude = (high - low) / 2
        data = tuple(0.0 if amplitude == 0 else (v - offset) / amplitude for v in wave.samples)
        return NodeSettings(
            FUNC_CUSTOM, wave.rate / len(wave.samples), amplitude, offset, 50.0, data
        )
    return NodeSettings(
        _FUNCTIONS[wave.kind], wave.frequency, wave.amplitude, wave.offset, wave.duty * 100.0
    )


@dataclass(frozen=True)
class DwfDeviceInfo:
    index: int
    serial: str
    name: str
    in_use: bool


class DwfLibrary:
    """The WaveForms SDK library; handles are the integers returned by ``open``."""

    def __init__(self, path: str | None = None) -> None:
        name = path or default_library()
        try:
            self._dll = _load(name)
        except OSError as exc:
            raise DeviceNotFound(
                f"WaveForms SDK library {name!r} cannot be loaded ({exc}); install "
                "WaveForms with the Adept runtime"
            ) from exc
        # generators started and not stopped, as (handle, channel)
        self._running: set[tuple[int, int]] = set()

    def _call(self, function: str, *args: Any) -> None:
        if not getattr(self._dll, function)(*args):
            raise DeviceError(f"WaveForms {function} failed: {self.last_error()}")

    def last_error(self) -> str:
        buffer = ctypes.create_string_buffer(512)
        self._dll.FDwfGetLastErrorMsg(buffer)
        return buffer.value.decode(errors="replace").strip() or "unknown error"

    # --- devices --------------------------------------------------------

    def devices(self) -> list[DwfDeviceInfo]:
        count = ctypes.c_int()
        self._call("FDwfEnum", ctypes.c_int(ENUM_ALL), ctypes.byref(count))
        found = []
        for index in range(count.value):
            serial = ctypes.create_string_buffer(32)
            name = ctypes.create_string_buffer(32)
            used = ctypes.c_int()
            self._call("FDwfEnumSN", ctypes.c_int(index), serial)
            self._call("FDwfEnumDeviceName", ctypes.c_int(index), name)
            self._call("FDwfEnumDeviceIsOpened", ctypes.c_int(index), ctypes.byref(used))
            found.append(
                DwfDeviceInfo(
                    index,
                    serial.value.decode(errors="replace").removeprefix("SN:"),
                    name.value.decode(errors="replace"),
                    bool(used.value),
                )
            )
        return found

    def open(self, index: int) -> int:
        """Open device ``index``; closing it later shuts the device down (outputs off)."""
        self._call("FDwfParamSet", ctypes.c_int(PARAM_ON_CLOSE), ctypes.c_int(ON_CLOSE_SHUTDOWN))
        handle = ctypes.c_int()
        self._call("FDwfDeviceOpen", ctypes.c_int(index), ctypes.byref(handle))
        if handle.value == 0:
            raise DeviceError(f"WaveForms FDwfDeviceOpen failed: {self.last_error()}")
        try:
            # settings take effect only on Configure (see the module docstring)
            self._call("FDwfDeviceAutoConfigureSet", handle, ctypes.c_int(0))
        except BaseException:
            self._dll.FDwfDeviceClose(handle)
            raise
        return handle.value

    def close(self, handle: int) -> None:
        self._running = {key for key in self._running if key[0] != handle}
        self._call("FDwfDeviceClose", ctypes.c_int(handle))

    # --- generators -----------------------------------------------------

    def awg_apply(self, handle: int, channel: int, wave: Waveform) -> None:
        """Set ``wave``; a running generator switches to it at once, a stopped one on start."""
        settings = node_settings(wave)
        h, ch, node = ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(NODE_CARRIER)
        self._call("FDwfAnalogOutNodeEnableSet", h, ch, node, ctypes.c_int(1))
        self._call("FDwfAnalogOutNodeFunctionSet", h, ch, node, ctypes.c_ubyte(settings.function))
        if settings.data is not None:
            data = (ctypes.c_double * len(settings.data))(*settings.data)
            self._call("FDwfAnalogOutNodeDataSet", h, ch, node, data, ctypes.c_int(len(data)))
        self._call(
            "FDwfAnalogOutNodeFrequencySet", h, ch, node, ctypes.c_double(settings.frequency)
        )
        self._call(
            "FDwfAnalogOutNodeAmplitudeSet", h, ch, node, ctypes.c_double(settings.amplitude)
        )
        self._call("FDwfAnalogOutNodeOffsetSet", h, ch, node, ctypes.c_double(settings.offset))
        self._call("FDwfAnalogOutNodeSymmetrySet", h, ch, node, ctypes.c_double(settings.symmetry))
        # a stopped generator outputs its offset
        self._call("FDwfAnalogOutIdleSet", h, ch, ctypes.c_int(IDLE_OFFSET))
        if (handle, channel) in self._running:
            self._call("FDwfAnalogOutConfigure", h, ch, ctypes.c_int(AWG_APPLY))

    def awg_start(self, handle: int, channel: int) -> None:
        """Apply the settings and start the generator."""
        # marked before the call: if it fails, the generator may still be running
        self._running.add((handle, channel))
        self._call(
            "FDwfAnalogOutConfigure",
            ctypes.c_int(handle),
            ctypes.c_int(channel),
            ctypes.c_int(AWG_START),
        )

    def awg_stop(self, handle: int, channel: int) -> None:
        """Set 0 V DC and stop; the idle output is the offset, i.e. 0 V."""
        self.awg_apply(handle, channel, Waveform.dc(0.0))
        self._call(
            "FDwfAnalogOutConfigure",
            ctypes.c_int(handle),
            ctypes.c_int(channel),
            ctypes.c_int(AWG_STOP),
        )
        self._running.discard((handle, channel))

    def awg_max_samples(self, handle: int, channel: int) -> int:
        low, high = ctypes.c_int(), ctypes.c_int()
        self._call(
            "FDwfAnalogOutNodeDataInfo",
            ctypes.c_int(handle),
            ctypes.c_int(channel),
            ctypes.c_int(NODE_CARRIER),
            ctypes.byref(low),
            ctypes.byref(high),
        )
        return high.value

    # --- scope ----------------------------------------------------------

    def scope_setup(self, handle: int, range_v: float) -> None:
        """Enable both scope channels with range ``range_v`` (peak to peak), offset 0."""
        h = ctypes.c_int(handle)
        for channel in (0, 1):
            ch = ctypes.c_int(channel)
            self._call("FDwfAnalogInChannelEnableSet", h, ch, ctypes.c_int(1))
            self._call("FDwfAnalogInChannelRangeSet", h, ch, ctypes.c_double(range_v))
            self._call("FDwfAnalogInChannelOffsetSet", h, ch, ctypes.c_double(0.0))
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(1), ctypes.c_int(0))

    def scope_max_samples(self, handle: int) -> int:
        low, high = ctypes.c_int(), ctypes.c_int()
        self._call(
            "FDwfAnalogInBufferSizeInfo",
            ctypes.c_int(handle),
            ctypes.byref(low),
            ctypes.byref(high),
        )
        return high.value

    def scope_acquire(
        self, handle: int, channel: int, rate: float, n: int, record: bool, timeout_s: float
    ) -> NDArray[np.float64]:
        """``n`` samples at ``rate``; ``record`` streams more samples than the buffer holds."""
        h, ch = ctypes.c_int(handle), ctypes.c_int(channel)
        self._call("FDwfAnalogInFrequencySet", h, ctypes.c_double(rate))
        actual = ctypes.c_double()
        self._call("FDwfAnalogInFrequencyGet", h, ctypes.byref(actual))
        if abs(actual.value - rate) > 0.001 * rate:
            _log.warning(
                "scope sample rate rounded by the device: requested %s Hz, actual %s Hz",
                rate,
                actual.value,
            )
        deadline = clock.now() + timeout_s
        if record:
            return self._record(h, ch, rate, n, deadline, timeout_s)
        self._call("FDwfAnalogInAcquisitionModeSet", h, ctypes.c_int(ACQ_SINGLE))
        self._call("FDwfAnalogInBufferSizeSet", h, ctypes.c_int(n))
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(1), ctypes.c_int(1))
        state = ctypes.c_ubyte()
        while True:
            self._call("FDwfAnalogInStatus", h, ctypes.c_int(1), ctypes.byref(state))
            if state.value == STATE_DONE:
                break
            if clock.now() > deadline:
                raise DeviceTimeout(f"scope acquisition did not finish within {timeout_s} s")
            time.sleep(_POLL_S)
        buffer = (ctypes.c_double * n)()
        self._call("FDwfAnalogInStatusData", h, ch, buffer, ctypes.c_int(n))
        return np.ctypeslib.as_array(buffer).astype(np.float64)

    def _record(
        self,
        h: ctypes.c_int,
        ch: ctypes.c_int,
        rate: float,
        n: int,
        deadline: float,
        timeout_s: float,
    ) -> NDArray[np.float64]:
        self._call("FDwfAnalogInAcquisitionModeSet", h, ctypes.c_int(ACQ_RECORD))
        self._call("FDwfAnalogInRecordLengthSet", h, ctypes.c_double(0.0))  # 0 = unlimited
        # reconfigure: apply the rate, mode and length set above (AutoConfigure is off)
        self._call("FDwfAnalogInConfigure", h, ctypes.c_int(1), ctypes.c_int(1))
        chunks: list[NDArray[np.float64]] = []
        got = 0
        state = ctypes.c_ubyte()
        available, lost, corrupt = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        try:
            while got < n:
                if clock.now() > deadline:
                    raise DeviceTimeout(f"scope record did not finish within {timeout_s} s")
                self._call("FDwfAnalogInStatus", h, ctypes.c_int(1), ctypes.byref(state))
                self._call(
                    "FDwfAnalogInStatusRecord",
                    h,
                    ctypes.byref(available),
                    ctypes.byref(lost),
                    ctypes.byref(corrupt),
                )
                if lost.value or corrupt.value:
                    raise DeviceError(
                        f"scope record lost {lost.value} and corrupted {corrupt.value} "
                        "samples; lower the sample rate"
                    )
                if available.value:
                    chunk = (ctypes.c_double * available.value)()
                    self._call("FDwfAnalogInStatusData", h, ch, chunk, available)
                    chunks.append(np.ctypeslib.as_array(chunk).astype(np.float64))
                    got += available.value
                elif state.value == STATE_DONE:
                    break
                else:
                    time.sleep(_POLL_S)
        finally:
            self._dll.FDwfAnalogInConfigure(h, ctypes.c_int(0), ctypes.c_int(0))
        data = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float64)
        if len(data) < n:
            raise DeviceError(f"scope record returned {len(data)} of {n} samples")
        return data[:n]
