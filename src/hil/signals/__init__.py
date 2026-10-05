"""Signal objects: one per wired terminal, typed by the terminal kind."""

from hil.signals.base import Signal
from hil.signals.digital import SenseRecording, SenseSignal, SwitchSignal
from hil.signals.fault import FaultPath
from hil.signals.power import PowerSignal

__all__ = [
    "FaultPath",
    "PowerSignal",
    "SenseRecording",
    "SenseSignal",
    "Signal",
    "SwitchSignal",
]
