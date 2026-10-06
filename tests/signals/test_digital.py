import threading
import time
from types import SimpleNamespace

import pytest

from hil.drivers.sim.di import SimDi, SimDiConfig
from hil.errors import DeviceTimeout, TerminationRequested, WaitTimeout
from hil.recording import Recorder
from hil.resources import DigitalInput
from hil.signals import SenseSignal, SwitchSignal


@pytest.fixture
def loop(relay_bank):
    di = SimDi("di1", SimDiConfig(inputs=2, mirror={0: "rel1.2"}))
    di.bind({"rel1": relay_bank})
    di.open()
    switch = SwitchSignal("X1.1", Recorder(), relay_bank.resource("2"))
    sense = SenseSignal("X2.1", Recorder(), di.resource("0"))
    return switch, sense


def test_switch_set(loop, relay_bank):
    switch, _ = loop
    assert switch.last_change is None
    switch.set(True)
    assert relay_bank.states[2] is True
    assert switch.state is True
    assert switch.last_change is not None


def test_switch_pulse(loop, relay_bank):
    switch, _ = loop
    switch.pulse(0.02)
    assert relay_bank.states[2] is False
    t_on, t_off = relay_bank.history[-2][0], relay_bank.history[-1][0]
    assert 0.02 <= t_off - t_on < 0.12


def test_switch_safe_state(loop, relay_bank):
    switch, _ = loop
    switch.set(True)
    switch.safe_state()
    assert relay_bank.states[2] is False


def test_sense_wait_for(loop):
    switch, sense = loop
    assert sense.read() is False
    switch.set(True)
    t = sense.wait_for(True, timeout=0.5)
    assert t >= switch.last_change


def test_sense_wait_for_timeout(loop):
    _, sense = loop
    start = time.perf_counter()
    with pytest.raises(WaitTimeout, match=r"X2\.1"):
        sense.wait_for(True, timeout=0.05)
    assert time.perf_counter() - start < 0.5


def test_sense_record(loop):
    switch, sense = loop
    with sense.record() as recording:
        switch.set(True)
        time.sleep(0.03)
        switch.set(False)
        time.sleep(0.03)
    assert [state for _, state in recording.changes] == [False, True, False]
    assert recording.samples > 2
    assert recording.mean_period_s > 0


class _StuckBank:
    name = "stuck"

    def __init__(self):
        self.release = threading.Event()

    def read(self, index):
        self.release.wait(5)
        return False


def test_record_times_out_on_stuck_input(monkeypatch):
    import hil.signals.digital

    monkeypatch.setattr(hil.signals.digital, "_START_TIMEOUT_S", 0.1)
    bank = _StuckBank()
    sense = SenseSignal("X2.1", Recorder(), DigitalInput(bank, 0))
    try:
        with pytest.raises(DeviceTimeout, match="first reading"), sense.record():
            pass
    finally:
        bank.release.set()


def test_termination_while_starting_record_stops_the_thread(loop, monkeypatch):
    import hil.signals.digital

    _, sense = loop
    events = []

    class InterruptedEvent(threading.Event):
        """The second event of record() is ``started``; its wait gets a signal."""

        def __init__(self):
            super().__init__()
            events.append(self)

        def wait(self, timeout=None):
            if self is events[1]:
                raise TerminationRequested("SIGTERM")
            return super().wait(timeout)

    fake_threading = SimpleNamespace(Event=InterruptedEvent, Thread=threading.Thread)
    monkeypatch.setattr(hil.signals.digital, "threading", fake_threading)
    with pytest.raises(TerminationRequested), sense.record():
        pass
    stop = events[0]
    assert stop.is_set()
    monkeypatch.undo()
    deadline = time.perf_counter() + 2
    while any(t.name == "hil-record-X2.1" for t in threading.enumerate()):
        assert time.perf_counter() < deadline, "recording thread still runs"
        time.sleep(0.01)
