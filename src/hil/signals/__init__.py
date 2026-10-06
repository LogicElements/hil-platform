"""Signal objects: one per wired terminal, typed by the terminal kind."""

from hil.signals.base import Signal
from hil.signals.digital import SenseRecording, SenseSignal, SwitchSignal
from hil.signals.fault import FaultPath
from hil.signals.port import PortSignal
from hil.signals.power import PowerSignal
from hil.signals.rs485 import Rs485Monitor, Rs485Signal
from hil.signals.uart import SerialSignal

__all__ = [
    "FaultPath",
    "PortSignal",
    "PowerSignal",
    "Rs485Monitor",
    "Rs485Signal",
    "SenseRecording",
    "SenseSignal",
    "SerialSignal",
    "Signal",
    "SwitchSignal",
]
