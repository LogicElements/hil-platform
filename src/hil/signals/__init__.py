"""Signal objects: one per wired terminal, typed by the terminal kind."""

from hil.signals.analog import (
    DEFAULT_RATE_HZ,
    AnalogIn,
    AnalogOut,
    AnalogRouter,
    Measurement,
    ScopeMux,
    measurement_of,
)
from hil.signals.base import Signal
from hil.signals.debug import DebugSignal
from hil.signals.digital import LogicOutSignal, SenseRecording, SenseSignal, SwitchSignal
from hil.signals.fault import FaultPath
from hil.signals.port import PortSignal
from hil.signals.power import PowerSignal
from hil.signals.rs485 import Rs485Monitor, Rs485Signal
from hil.signals.uart import SerialSignal

__all__ = [
    "DEFAULT_RATE_HZ",
    "AnalogIn",
    "AnalogOut",
    "AnalogRouter",
    "DebugSignal",
    "FaultPath",
    "LogicOutSignal",
    "Measurement",
    "PortSignal",
    "PowerSignal",
    "Rs485Monitor",
    "Rs485Signal",
    "ScopeMux",
    "SenseRecording",
    "SenseSignal",
    "SerialSignal",
    "Signal",
    "SwitchSignal",
    "measurement_of",
]
