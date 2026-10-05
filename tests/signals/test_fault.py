import pytest

from hil.errors import OperationNotAllowed, SignalUnavailable
from hil.recording import Recorder
from hil.signals import FaultPath


def make(bank, short=True, **flags):
    return FaultPath(
        "F1",
        Recorder(),
        series=bank.resource("6"),
        short=bank.resource("7") if short else None,
        **flags,
    )


def test_open(relay_bank):
    path = make(relay_bank)
    path.open()
    assert relay_bank.states[6:8] == [True, False]
    assert path.state == "open"


def test_short_keeps_wire_connected(relay_bank):
    path = make(relay_bank)
    path.open()
    path.short_to_gnd()
    assert relay_bank.states[6:8] == [False, True]
    assert path.state == "short"
    assert relay_bank.history[-1][1] == {6: False, 7: True}


def test_restore_and_safe_state(relay_bank):
    path = make(relay_bank)
    path.short_to_gnd()
    path.restore()
    assert relay_bank.states[6:8] == [False, False]
    path.open()
    path.safe_state()
    assert path.state == "ok"


def test_short_without_short_relay(relay_bank):
    path = make(relay_bank, short=False)
    path.open()
    path.restore()
    with pytest.raises(SignalUnavailable, match="no short-to-ground relay"):
        path.short_to_gnd()


def test_short_on_power_path_needs_permission(relay_bank):
    path = make(relay_bank, carries_power=True)
    with pytest.raises(OperationNotAllowed, match="allow_short"):
        path.short_to_gnd()
    assert relay_bank.states[7] is False
    allowed = make(relay_bank, carries_power=True, allow_short=True)
    allowed.short_to_gnd()
    assert relay_bank.states[7] is True
