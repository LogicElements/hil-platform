import pytest
from pydantic import ValidationError

from hil.config.models import (
    AnalogOutTerminal,
    DebugParams,
    DutConfig,
    FaultPathTerminal,
    PowerTerminal,
    Profile,
    SerialParams,
    StationConfig,
    signal_params,
    terminal_refs,
)
from hil.config.refs import ResourceRef


def station(**overrides):
    data = {
        "name": "t",
        "profile": "standard-v1",
        "devices": {"rel1": {"driver": "sim_relay", "channels": 8}},
        "terminals": {
            "PWR": {"kind": "power", "relays": ["rel1.0", "rel1.1"]},
            "X1.1": {"kind": "switch", "relay": "rel1.2"},
        },
    }
    data.update(overrides)
    return StationConfig.model_validate(data)


def test_valid_station():
    cfg = station()
    assert isinstance(cfg.terminals["PWR"], PowerTerminal)
    assert cfg.devices["rel1"].driver == "sim_relay"
    assert cfg.devices["rel1"].options() == {"channels": 8}


def test_unknown_device():
    with pytest.raises(ValidationError, match="unknown device 'rel9'"):
        station(terminals={"X1.1": {"kind": "switch", "relay": "rel9.2"}})


def test_resource_used_twice():
    with pytest.raises(ValidationError, match=r"rel1\.2 is used by both 'X1\.1' and 'X1\.2'"):
        station(
            terminals={
                "X1.1": {"kind": "switch", "relay": "rel1.2"},
                "X1.2": {"kind": "switch", "relay": "rel1.2"},
            }
        )


def test_unknown_kind():
    with pytest.raises(ValidationError):
        station(terminals={"X1.1": {"kind": "lamp", "relay": "rel1.2"}})


def test_extra_field_is_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        station(terminals={"X1.1": {"kind": "switch", "relay": "rel1.2", "typo": 1}})


def test_device_name_with_dot_is_rejected():
    with pytest.raises(ValidationError, match="device name"):
        station(devices={"rel.1": {"driver": "sim_relay"}}, terminals={})


def test_debug_terminal_checks_probe_device():
    with pytest.raises(ValidationError, match="unknown device 'stlink'"):
        station(terminals={"SWD": {"kind": "debug", "probe": "stlink"}})


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"select": "a.1"},
        {"direct": "a.1", "select": "a.2", "connect": "a.3"},
        {"direct": "a.1", "connect": "a.3"},
    ],
)
def test_analog_out_needs_direct_or_mux(fields):
    with pytest.raises(ValidationError, match="either 'direct'"):
        AnalogOutTerminal.model_validate({"kind": "analog_out", **fields})


@pytest.mark.parametrize("fields", [{"direct": "a.1"}, {"select": "a.2", "connect": "a.3"}])
def test_analog_out_valid(fields):
    AnalogOutTerminal.model_validate({"kind": "analog_out", **fields})


def test_terminal_refs():
    t = FaultPathTerminal.model_validate({"kind": "fault_path", "series": "r.1", "short": "r.2"})
    assert terminal_refs(t) == [ResourceRef("r", "1"), ResourceRef("r", "2")]
    p = PowerTerminal.model_validate({"kind": "power", "relays": ["r.0", "r.1"]})
    assert terminal_refs(p) == [ResourceRef("r", "0"), ResourceRef("r", "1")]


def test_profile():
    profile = Profile.model_validate({"profile": "p", "terminals": {"PWR": "power"}})
    assert profile.terminals == {"PWR": "power"}
    with pytest.raises(ValidationError):
        Profile.model_validate({"profile": "p", "terminals": {"PWR": "lamp"}})


def test_dut_shorthand_and_params():
    dut = DutConfig.model_validate(
        {
            "dut": "d",
            "profile": "standard-v1",
            "signals": {"supply": "PWR", "console": {"terminal": "CON", "baud": 115200}},
        }
    )
    assert dut.signals["supply"].terminal == "PWR"
    assert dut.signals["supply"].params() == {}
    assert dut.signals["console"].params() == {"baud": 115200}


@pytest.mark.parametrize("name", ["door-sensor", "1st", "class", "_hidden", "params", "name"])
def test_dut_rejects_bad_signal_names(name):
    with pytest.raises(ValidationError, match="signal name"):
        DutConfig.model_validate({"dut": "d", "profile": "p", "signals": {name: "PWR"}})


def test_serial_params_defaults_and_gap():
    params = SerialParams()
    assert (params.baud, params.parity, params.stopbits, params.bytesize) == (115200, "N", 1, 8)
    assert SerialParams(baud=9600).gap_s() == pytest.approx(3.5 * 10 / 9600)
    assert SerialParams(baud=921600, parity="E").gap_s() == 0.0015
    assert SerialParams(frame_gap_s=0.01).gap_s() == 0.01
    assert SerialParams(baud=19200, parity="E").char_time_s() == pytest.approx(11 / 19200)


def test_signal_params():
    assert signal_params("power", {}) is None
    params = signal_params("rs485", {"baud": 19200, "parity": "E"})
    assert params == SerialParams(baud=19200, parity="E")
    with pytest.raises(ValueError, match="takes no parameters"):
        signal_params("switch", {"baud": 1})
    with pytest.raises(ValidationError):
        signal_params("serial", {"parity": "X"})


def test_debug_params():
    params = signal_params("debug", {"target": "target/stm32g4x.cfg"})
    assert params == DebugParams(target="target/stm32g4x.cfg", timeout_s=120.0)
    with pytest.raises(ValidationError):
        signal_params("debug", {})
    with pytest.raises(ValidationError):
        signal_params("debug", {"target": "t.cfg", "speed": 4000})


ANALOG_DEVICES = {
    "rel1": {"driver": "sim_relay", "channels": 8},
    "rel2": {"driver": "sim_relay", "channels": 16},
    "ad3": {"driver": "sim_ad3"},
}


def analog_station(terminals, analog=None):
    data = {"devices": ANALOG_DEVICES, "terminals": terminals}
    if analog is not None:
        data["analog"] = analog
    return station(**data)


def test_analog_section():
    cfg = analog_station(
        {
            "AO.0": {"kind": "analog_out", "direct": "ad3.awg1"},
            "AO.1": {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"},
        },
        analog={"generators": ["ad3.awg1", "ad3.awg2"]},
    )
    assert cfg.analog is not None
    assert [str(g) for g in cfg.analog.generators] == ["ad3.awg1", "ad3.awg2"]


def test_station_without_analog_section():
    assert station().analog is None


def test_mux_output_needs_analog_section():
    with pytest.raises(ValidationError, match=r"'AO.1' uses the output multiplexer"):
        analog_station({"AO.1": {"kind": "analog_out", "select": "rel2.0", "connect": "rel2.1"}})


@pytest.mark.parametrize("generators", [["ad3.awg1"], ["ad3.awg1", "ad3.awg2", "ad3.awg1"]])
def test_analog_needs_two_generators(generators):
    with pytest.raises(ValidationError, match="generators"):
        analog_station({}, analog={"generators": generators})


def test_analog_generators_differ():
    with pytest.raises(ValidationError, match="must differ"):
        analog_station({}, analog={"generators": ["ad3.awg1", "ad3.awg1"]})


def test_analog_generator_unknown_device():
    with pytest.raises(ValidationError, match=r"generator nope.awg1 refers to unknown device"):
        analog_station({}, analog={"generators": ["nope.awg1", "ad3.awg2"]})


def test_generator_used_by_other_terminal():
    with pytest.raises(
        ValidationError, match=r"generator ad3.awg1 is also used by terminal 'X1.1'"
    ):
        analog_station(
            {"X1.1": {"kind": "switch", "relay": "ad3.awg1"}},
            analog={"generators": ["ad3.awg1", "ad3.awg2"]},
        )


def test_two_direct_outputs_on_one_generator():
    with pytest.raises(ValidationError, match=r"ad3.awg1 is used by both 'AO.0' and 'AO.1'"):
        analog_station(
            {
                "AO.0": {"kind": "analog_out", "direct": "ad3.awg1"},
                "AO.1": {"kind": "analog_out", "direct": "ad3.awg1"},
            }
        )


def test_shared_scope_with_connect_relays():
    cfg = analog_station(
        {
            "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
            "AI.2": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.9"},
        }
    )
    assert set(cfg.terminals) == {"AI.1", "AI.2"}


def test_shared_scope_needs_connect_relays():
    with pytest.raises(ValidationError, match=r"ad3.ch1 is shared by 'AI.1', 'AI.2'"):
        analog_station(
            {
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
                "AI.2": {"kind": "analog_in", "scope": "ad3.ch1"},
            }
        )


def test_scope_used_by_other_kind():
    with pytest.raises(ValidationError, match=r"ad3.ch1 is used by both 'X1.1' and 'AI.1'"):
        analog_station(
            {
                "X1.1": {"kind": "switch", "relay": "ad3.ch1"},
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1"},
            }
        )


def test_connect_relay_used_twice():
    with pytest.raises(ValidationError, match=r"rel2.8 is used by both 'AI.1' and 'AI.2'"):
        analog_station(
            {
                "AI.1": {"kind": "analog_in", "scope": "ad3.ch1", "connect": "rel2.8"},
                "AI.2": {"kind": "analog_in", "scope": "ad3.ch2", "connect": "rel2.8"},
            }
        )
