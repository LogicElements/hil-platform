import json
import math
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, ResourceConflict
from hil.recording import Recorder
from hil.resources import ScopeChannel
from hil.signals import AnalogIn, Measurement, ScopeMux, measurement_of


@pytest.fixture
def rig(tmp_path):
    rel = SimRelay("rel2", SimRelayConfig(channels=16))
    rel.open()
    ad3 = SimAd3(
        "ad3",
        SimAd3Config(
            inputs={"ch1": {"dc": 1.0, "sine": {"freq": 50, "amp": 0.5}}, "ch2": {"dc": -12.0}}
        ),
    )
    ad3.open()
    recorder = Recorder()
    recorder.start_test(tmp_path)
    ch1 = ad3.resource("ch1")
    mux1 = ScopeMux(ch1)
    ai1 = AnalogIn("AI.1", recorder, ch1, mux1, connect=rel.resource("8"), settle_s=0)
    ai2 = AnalogIn("AI.2", recorder, ch1, mux1, connect=rel.resource("9"), settle_s=0)
    ch2 = ad3.resource("ch2")
    ai3 = AnalogIn("AI.3", recorder, ch2, ScopeMux(ch2))
    yield SimpleNamespace(
        rel=rel, ad3=ad3, recorder=recorder, ai1=ai1, ai2=ai2, ai3=ai3, dir=tmp_path
    )
    recorder.stop_test()


def frames(rig):
    return [states for _, states in rig.rel.history]


def test_measurement_of():
    assert measurement_of(np.array([1.0, 3.0])) == Measurement(2.0, 1.0)
    with pytest.raises(ValueError):
        measurement_of(np.array([]))


def test_measure_dc_and_rms(rig):
    m = rig.ai1.measure()
    assert m.dc == pytest.approx(1.0, abs=1e-9)
    assert m.rms_ac == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
    assert rig.ad3.acquisitions[-1][1:] == (0, 100_000.0, 10_000)


def test_measure_without_multiplexer(rig):
    assert rig.ai3.measure(0.02).dc == pytest.approx(-12.0)
    assert rig.rel.history == []


def test_measure_is_recorded(rig):
    rig.ai1.measure(0.02)
    lines = (rig.dir / "measurements.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["terminal"] == "AI.1"
    assert record["dc"] == pytest.approx(1.0, abs=1e-9)
    assert (record["duration_s"], record["rate"]) == (0.02, 100_000.0)


def test_capture(rig):
    data = rig.ai3.capture(0.01, rate=10_000)
    assert len(data) == 100
    events = (rig.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    capture = [json.loads(e) for e in events if '"capture"' in e]
    assert capture[0]["samples"] == 100


def test_break_before_make(rig):
    rig.ai1.measure(0.02)
    rig.ai2.measure(0.02)
    assert frames(rig) == [{8: True}, {8: False}, {9: True}]
    assert rig.rel.states[8:10] == [False, True]


def test_connected_terminal_is_not_switched_again(rig):
    rig.ai1.measure(0.02)
    rig.ai1.measure(0.02)
    assert frames(rig) == [{8: True}]


def test_settle_time(rig):
    ch2 = rig.ad3.resource("ch2")
    ai = AnalogIn(
        "AI.4", rig.recorder, ch2, ScopeMux(ch2), connect=rig.rel.resource("10"), settle_s=0.05
    )
    ai.measure(0.001)
    connected_at = rig.rel.history[-1][0]
    acquired_at = rig.ad3.acquisitions[-1][0]
    assert acquired_at - connected_at >= 0.05


def test_reconnects_after_safe_state(rig):
    rig.ai1.measure(0.02)
    rig.ai1.safe_state()
    assert rig.rel.states[8] is False
    rig.ai1.measure(0.02)
    assert frames(rig) == [{8: True}, {8: False}, {8: True}]


def test_safe_state_without_connect_relay(rig):
    rig.ai3.safe_state()
    assert rig.rel.history == []


class SlowScope:
    name = "slow"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def scope_acquire(self, index, rate, n):
        self.entered.set()
        self.release.wait(5)
        return np.zeros(n)


def test_concurrent_measurement_conflicts(rig):
    slow = SlowScope()
    scope = ScopeChannel(slow, 0)
    mux = ScopeMux(scope)
    a = AnalogIn("AI.1", rig.recorder, scope, mux, connect=rig.rel.resource("12"), settle_s=0)
    b = AnalogIn("AI.2", rig.recorder, scope, mux, connect=rig.rel.resource("13"), settle_s=0)
    thread = threading.Thread(target=a.measure, args=(0.001,))
    thread.start()
    try:
        assert slow.entered.wait(5)
        with pytest.raises(
            ResourceConflict, match=r"AI.2: scope channel slow.ch1 is busy measuring AI.1"
        ):
            b.measure(0.001)
        assert rig.rel.states[12:14] == [True, False]
    finally:
        slow.release.set()
        thread.join(5)
    b.measure(0.001)
    assert rig.rel.states[12:14] == [False, True]


def test_shared_scope_needs_connect_relays(rig):
    ch2 = rig.ad3.resource("ch2")
    mux = ScopeMux(ch2)
    AnalogIn("AI.3", rig.recorder, ch2, mux, connect=rig.rel.resource("10"))
    with pytest.raises(ConfigError, match=r"share scope channel ad3.ch2"):
        AnalogIn("AI.4", rig.recorder, ch2, mux)


@pytest.mark.parametrize(("duration", "rate"), [(0, 1000), (0.1, 0), (-1, 1000)])
def test_invalid_acquisition(rig, duration, rate):
    with pytest.raises(ValueError):
        rig.ai3.measure(duration, rate)
