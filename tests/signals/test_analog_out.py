import json
from types import SimpleNamespace

import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, DeviceError, ResourceConflict
from hil.recording import Recorder
from hil.resources import Waveform
from hil.signals import AnalogOut, AnalogRouter


@pytest.fixture
def rig(tmp_path):
    rel = SimRelay("rel2", SimRelayConfig(channels=8))
    rel.open()
    ad3 = SimAd3("ad3", SimAd3Config())
    ad3.open()
    recorder = Recorder()
    recorder.start_test(tmp_path)
    router = AnalogRouter([ad3.resource("awg1"), ad3.resource("awg2")], recorder)
    out = {"AO.0": AnalogOut("AO.0", recorder, router, direct=ad3.resource("awg1"))}
    # AO.1: select rel2.0, connect rel2.1; AO.2: rel2.2, rel2.3; AO.3: rel2.4, rel2.5
    for i, name in enumerate(["AO.1", "AO.2", "AO.3"]):
        out[name] = AnalogOut(
            name,
            recorder,
            router,
            select=rel.resource(str(2 * i)),
            connect=rel.resource(str(2 * i + 1)),
        )
    yield SimpleNamespace(rel=rel, ad3=ad3, recorder=recorder, router=router, out=out, dir=tmp_path)
    recorder.stop_test()


def events(rig):
    lines = (rig.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    return [json.loads(line) for line in lines]


def frames(rig):
    return [states for _, states in rig.rel.history]


def test_mux_output_prefers_generator_without_direct_terminal(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"
    assert rig.out["AO.1"].waveform == Waveform.sine(1000, 1.0)
    assert rig.ad3.waves[1] == Waveform.sine(1000, 1.0)
    assert rig.ad3.running == [False, True]
    assert rig.rel.states[0:2] == [True, True]


def test_order_generator_then_select_then_connect(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    started = next(t for t, _, action, _ in rig.ad3.history if action == "start")
    assert frames(rig) == [{0: True}, {1: True}]
    assert started < rig.rel.history[0][0] < rig.rel.history[1][0]


def test_second_output_gets_generator_1_and_marks_direct_terminal(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    assert str(rig.out["AO.2"].generator) == "ad3.awg1"
    assert rig.rel.states[2:4] == [False, True]
    assert {2: True} not in frames(rig)
    shared = [e for e in events(rig) if e["action"] == "shared_generator"]
    assert len(shared) == 1
    assert (shared[0]["source"], shared[0]["generator"], shared[0]["by"]) == (
        "AO.0",
        "ad3.awg1",
        "AO.2",
    )


def test_no_free_generator(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    before = frames(rig)
    with pytest.raises(ResourceConflict, match=r"AO.3: both generators are in use"):
        rig.out["AO.3"].dc(1.0)
    assert frames(rig) == before


def test_direct_output_conflicts_with_mux_on_its_generator(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.2"].dc(1.5)
    with pytest.raises(ResourceConflict, match=r"AO.0: generator ad3.awg1 is in use by AO.2"):
        rig.out["AO.0"].dc(1.0)


def test_direct_output_keeps_its_generator(rig):
    rig.out["AO.0"].sine(10_000, 2.0)
    assert str(rig.out["AO.0"].generator) == "ad3.awg1"
    assert rig.rel.history == []
    rig.out["AO.1"].dc(1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"
    with pytest.raises(ResourceConflict):
        rig.out["AO.2"].dc(1.0)


def test_waveform_change_keeps_generator_and_relays(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    before = frames(rig)
    rig.out["AO.1"].dc(2.0)
    assert rig.ad3.waves[1] == Waveform.dc(2.0)
    assert rig.ad3.running[1]
    assert frames(rig) == before


def test_follow_shares_generator(rig):
    ao1, ao2 = rig.out["AO.1"], rig.out["AO.2"]
    ao1.sine(1000, 1.0)
    ao2.follow(ao1)
    assert ao2.generator == ao1.generator
    assert rig.rel.states[2:4] == [True, True]
    ao2.dc(1.5)
    assert ao1.waveform == Waveform.dc(1.5)
    assert ("AO.2", "follow") in [(e["source"], e["action"]) for e in events(rig)]


def test_follow_needs_a_signal(rig):
    with pytest.raises(ResourceConflict, match=r"AO.2: AO.1 has no signal to follow"):
        rig.out["AO.2"].follow(rig.out["AO.1"])


def test_follow_itself(rig):
    rig.out["AO.1"].dc(1.0)
    with pytest.raises(ValueError, match="cannot follow itself"):
        rig.out["AO.1"].follow(rig.out["AO.1"])


def test_follow_moves_terminal_and_frees_old_generator(rig):
    ao1, ao2 = rig.out["AO.1"], rig.out["AO.2"]
    ao1.sine(1000, 1.0)  # generator 2
    ao2.dc(1.5)  # generator 1, select released
    rig.rel.history.clear()
    ao2.follow(ao1)
    assert frames(rig) == [{3: False}, {2: True}, {3: True}]
    assert rig.ad3.running == [False, True]
    assert ao2.generator == ao1.generator


def test_disconnect_stops_generator_when_last_terminal_leaves(rig):
    ao1, ao2, ao3 = rig.out["AO.1"], rig.out["AO.2"], rig.out["AO.3"]
    ao1.sine(1000, 1.0)
    ao2.follow(ao1)
    ao1.disconnect()
    assert rig.rel.states[1] is False
    assert rig.ad3.running[1]
    ao2.disconnect()
    assert rig.ad3.running == [False, False]
    assert ao1.generator is None
    assert ao2.waveform is None
    ao3.dc(1.0)
    assert str(ao3.generator) == "ad3.awg2"


def test_direct_output_follow_rules(rig):
    ao0, ao1 = rig.out["AO.0"], rig.out["AO.1"]
    ao1.sine(1000, 1.0)  # generator 2
    with pytest.raises(ResourceConflict, match=r"wired directly to ad3.awg1"):
        ao0.follow(ao1)
    ao1.disconnect()
    ao0.sine(10_000, 1.0)
    ao1.follow(ao0)
    assert str(ao1.generator) == "ad3.awg1"
    assert rig.rel.states[0:2] == [False, True]


def test_safe_state_releases_everything(rig):
    rig.out["AO.1"].dc(1.0)
    rig.out["AO.2"].follow(rig.out["AO.1"])
    rig.out["AO.3"].dc(2.0)
    for out in rig.out.values():
        out.safe_state()
    assert rig.rel.states[:6] == [False] * 6
    assert rig.ad3.running == [False, False]
    rig.out["AO.3"].dc(1.0)
    rig.out["AO.0"].dc(1.0)


def test_safe_state_frees_generator_even_if_relay_fails(rig):
    rig.out["AO.1"].dc(1.0)
    rig.rel.fail_with = DeviceError("bus timeout")
    with pytest.raises(DeviceError, match="bus timeout"):
        rig.out["AO.1"].safe_state()
    assert rig.out["AO.1"].generator is None
    assert rig.ad3.running == [False, False]


def test_failed_routing_stops_generator(rig):
    rig.rel.fail_with = DeviceError("bus timeout")
    with pytest.raises(DeviceError, match="bus timeout"):
        rig.out["AO.1"].sine(1000, 1.0)
    assert rig.out["AO.1"].generator is None
    assert rig.ad3.running == [False, False]
    rig.rel.fail_with = None
    rig.out["AO.1"].sine(1000, 1.0)
    assert str(rig.out["AO.1"].generator) == "ad3.awg2"


def test_out_of_range_voltage_switches_nothing(rig):
    with pytest.raises(ValueError, match="exceeds the generator range"):
        rig.out["AO.1"].sine(1000, 4.0, offset=2.0)
    assert rig.rel.history == []
    assert rig.ad3.running == [False, False]
    assert rig.out["AO.1"].generator is None


def test_square_and_arbitrary(rig):
    rig.out["AO.1"].square(100, 1.0, duty=0.2)
    assert rig.ad3.waves[1] == Waveform.square(100, 1.0, duty=0.2)
    rig.out["AO.1"].arbitrary([0.0, 1.0, 0.5], rate=3000)
    assert rig.ad3.waves[1] == Waveform.arbitrary([0.0, 1.0, 0.5], rate=3000)


def test_waveform_event(rig):
    rig.out["AO.1"].sine(1000, 1.0)
    rig.out["AO.1"].disconnect()
    recorded = events(rig)
    waveform = next(e for e in recorded if e["action"] == "waveform")
    assert (waveform["source"], waveform["generator"], waveform["kind"], waveform["freq"]) == (
        "AO.1",
        "ad3.awg2",
        "sine",
        1000.0,
    )
    assert ("AO.1", "disconnect") in [(e["source"], e["action"]) for e in recorded]


def test_configuration_errors(rig):
    with pytest.raises(ConfigError, match=r"both wired to generator ad3.awg1"):
        AnalogOut("AO.4", rig.recorder, rig.router, direct=rig.ad3.resource("awg1"))
    with pytest.raises(ConfigError, match="no 'analog' generators"):
        AnalogOut(
            "AO.4",
            rig.recorder,
            AnalogRouter([], rig.recorder),
            select=rig.rel.resource("6"),
            connect=rig.rel.resource("7"),
        )
    with pytest.raises(ConfigError, match="either a direct generator"):
        AnalogOut("AO.4", rig.recorder, rig.router)
    with pytest.raises(ConfigError, match="needs 2 generators"):
        AnalogRouter([rig.ad3.resource("awg1")], rig.recorder)
