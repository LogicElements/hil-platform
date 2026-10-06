import pytest

from hil.config.models import AnalogConfig, AnalogOutTerminal
from hil.errors import ConfigError, DeviceError, ResourceConflict, SignalUnavailable
from hil.signals import AnalogIn, AnalogOut
from hil.station import Station, _devices_of

STATION = """
name: t
profile: standard-v1
devices:
  rel1: {driver: sim_relay, channels: 8}
  rel2: {driver: sim_relay, channels: 16}
  ad3: {driver: sim_ad3, inputs: {ch1: {dc: 2.0}}}
analog:
  generators: [ad3.awg1, ad3.awg2]
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  AO.0: {kind: analog_out, direct: ad3.awg1}
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AO.2: {kind: analog_out, select: rel2.2, connect: rel2.3}
  AI.1: {kind: analog_in, scope: ad3.ch1, connect: rel2.8, settle_s: 0}
  AI.2: {kind: analog_in, scope: ad3.ch1, connect: rel2.9, settle_s: 0}
"""


def make(tmp_path, text=STATION) -> Station:
    path = tmp_path / "station.yaml"
    path.write_text(text, encoding="utf-8")
    return Station.from_files(path)


def test_analog_terminals_and_block(tmp_path):
    station = make(tmp_path)
    assert isinstance(station.terminals["AO.1"], AnalogOut)
    assert isinstance(station.terminals["AI.1"], AnalogIn)
    assert list(station.analog.outputs) == ["AO.0", "AO.1", "AO.2"]
    assert list(station.analog.inputs) == ["AI.1", "AI.2"]
    assert station.terminals["AI.1"].mux is station.terminals["AI.2"].mux


def test_block_operations(tmp_path):
    with make(tmp_path) as station:
        rel2, ad3 = station.devices["rel2"], station.devices["ad3"]
        station.analog.sine("AO.1", 1000, 1.0)
        assert rel2.states[0:2] == [True, True]
        station.analog.follow("AO.2", "AO.1")
        assert station.analog.output("AO.2").generator == station.analog.output("AO.1").generator
        assert station.analog.measure("AI.2", 0.01).dc == pytest.approx(2.0)
        assert rel2.states[8:10] == [False, True]
        assert len(station.analog.capture("AI.1", 0.001, rate=10_000)) == 10
        station.analog.disconnect_all()
        assert ad3.running == [False, False]
        assert rel2.states[1] is False
        assert rel2.states[3] is False


def test_block_lookup(tmp_path):
    station = make(tmp_path)
    with pytest.raises(SignalUnavailable, match=r"no analog_out terminal 'AO.3'"):
        station.analog.output("AO.3")
    with pytest.raises(ConfigError, match=r"'AI.1' is a analog_in terminal, not a analog_out"):
        station.analog.output("AI.1")


def test_safe_state(tmp_path):
    with make(tmp_path) as station:
        station.analog.sine("AO.1", 1000, 1.0)
        station.analog.dc("AO.0", 1.0)
        station.analog.measure("AI.1", 0.01)
        station.safe_state()
        assert station.devices["rel2"].states == [False] * 16
        assert station.devices["ad3"].running == [False, False]
        assert station.analog.output("AO.1").generator is None


def test_generators_free_after_safe_state(tmp_path):
    with make(tmp_path) as station:
        station.analog.dc("AO.1", 1.0)
        station.analog.dc("AO.2", 2.0)
        with pytest.raises(ResourceConflict):
            station.analog.dc("AO.0", 1.0)
        station.devices["rel2"].fail_with = DeviceError("bus timeout")
        with pytest.raises(DeviceError):
            station.safe_state()
        station.devices["rel2"].fail_with = None
        station.analog.dc("AO.1", 1.0)
        station.analog.dc("AO.2", 2.0)


def test_generator_must_be_awg(tmp_path):
    text = STATION.replace("generators: [ad3.awg1, ad3.awg2]", "generators: [rel1.5, ad3.awg2]")
    with pytest.raises(ConfigError, match=r"analog generator rel1.5 is not an AwgChannel"):
        make(tmp_path, text)


def test_direct_output_on_relay(tmp_path):
    with pytest.raises(ConfigError, match=r"terminal 'AO.0': rel1.5 is not a AwgChannel"):
        make(tmp_path, STATION.replace("direct: ad3.awg1", "direct: rel1.5"))


def test_mux_output_depends_on_generator_devices():
    terminal = AnalogOutTerminal.model_validate(
        {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"}
    )
    analog = AnalogConfig.model_validate({"generators": ["ad3.awg1", "ad3.awg2"]})
    assert _devices_of(terminal, analog) == {"rel2", "ad3"}
    assert _devices_of(terminal, None) == {"rel2"}
