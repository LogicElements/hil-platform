import time

import pytest

from hil.drivers.sim.di import SimDi, SimDiConfig
from hil.errors import WaitTimeout
from hil.recording import Recorder
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
