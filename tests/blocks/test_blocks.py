import pytest

from hil.blocks import DigitalBlock, FaultMatrix, PowerBlock
from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, DeviceError, SignalUnavailable
from hil.recording import Recorder
from hil.resources import LogicOutput
from hil.signals import FaultPath, LogicOutSignal, PowerSignal, SwitchSignal


def test_unknown_terminal_is_unavailable():
    with pytest.raises(SignalUnavailable, match="no power terminal 'PWR'"):
        PowerBlock({}).on("PWR")
    with pytest.raises(SignalUnavailable, match=r"no switch terminal 'X1.1'"):
        DigitalBlock({}, {}).set("X1.1", True)
    with pytest.raises(SignalUnavailable, match="no fault_path terminal 'F1'"):
        FaultMatrix({}).open("F1")


def test_emergency_off_continues_after_failure(relay_bank):
    broken = SimRelay("rel2", SimRelayConfig(channels=2))
    broken.open()
    a = PowerSignal("A", Recorder(), [broken.resource("0")])
    b = PowerSignal("B", Recorder(), [relay_bank.resource("0")])
    block = PowerBlock({"A": a, "B": b})
    block.on("A")
    block.on("B")
    broken.fail_with = DeviceError("bus down")
    errors = block.emergency_off()
    assert [str(e) for e in errors] == ["bus down"]
    assert relay_bank.states[0] is False


def test_digital_block(relay_bank):
    block = DigitalBlock({"X1.1": SwitchSignal("X1.1", Recorder(), relay_bank.resource("2"))}, {})
    block.set("X1.1", True)
    assert relay_bank.states[2] is True


def test_restore_all(relay_bank):
    f1 = FaultPath("F1", Recorder(), relay_bank.resource("4"), None)
    f2 = FaultPath("F2", Recorder(), relay_bank.resource("5"), None)
    matrix = FaultMatrix({"F1": f1, "F2": f2})
    matrix.open("F1")
    matrix.open("F2")
    matrix.restore_all()
    assert (f1.state, f2.state) == ("ok", "ok")


class _Outputs:
    name = "dio"

    def drive(self, index, value):
        pass

    def release(self, index):
        pass


def test_digital_block_logic_out():
    signal = LogicOutSignal("X3.1", Recorder(), LogicOutput(_Outputs(), 8))
    profile = {"X3.1": "logic_out", "X3.2": "logic_out", "X2.1": "sense"}
    block = DigitalBlock({}, {}, profile, logic_outs={"X3.1": signal})
    assert block.logic_out("X3.1") is signal
    with pytest.raises(SignalUnavailable, match=r"no logic_out terminal 'X3.2'"):
        block.logic_out("X3.2")
    with pytest.raises(ConfigError, match="is a sense terminal, not a logic_out"):
        block.logic_out("X2.1")
