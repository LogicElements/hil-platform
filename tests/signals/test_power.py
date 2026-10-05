import json

import pytest

from hil import clock
from hil.errors import OperationNotAllowed
from hil.recording import Recorder
from hil.signals import PowerSignal
from hil.signals.timing import precise_sleep


@pytest.fixture
def power(relay_bank):
    return PowerSignal("PWR", Recorder(), [relay_bank.resource("0"), relay_bank.resource("1")])


def test_on_switches_both_poles_in_one_operation(power, relay_bank):
    power.on()
    assert relay_bank.states[:2] == [True, True]
    assert relay_bank.history[-1][1] == {0: True, 1: True}
    assert len(relay_bank.history) == 1
    assert power.is_on


def test_off(power, relay_bank):
    power.on()
    power.off()
    assert relay_bank.states[:2] == [False, False]
    assert not power.is_on


def test_outage_duration(power, relay_bank):
    power.on()
    actual = power.outage(0.05)
    assert 0.05 <= actual < 0.15
    assert relay_bank.states[:2] == [True, True]
    assert [h[1] for h in relay_bank.history[-2:]] == [{0: False, 1: False}, {0: True, 1: True}]


def test_outage_requires_power_on(power, relay_bank):
    with pytest.raises(OperationNotAllowed, match="switched on"):
        power.outage(0.1)
    assert relay_bank.states[:2] == [False, False]


@pytest.mark.parametrize("duration", [0, -1])
def test_outage_rejects_non_positive_duration(power, duration):
    power.on()
    with pytest.raises(ValueError, match="positive"):
        power.outage(duration)


def test_cycle(power, relay_bank):
    power.cycle(3, on_s=0.0, off_s=0.0)
    assert len(relay_bank.history) == 6
    assert power.is_on


def test_cycle_rejects_bad_arguments(power):
    with pytest.raises(ValueError):
        power.cycle(0, 0.1, 0.1)
    with pytest.raises(ValueError):
        power.cycle(1, -0.1, 0.1)


def test_safe_state_is_off(power, relay_bank):
    power.on()
    power.safe_state()
    assert not power.is_on


def test_needs_relays():
    with pytest.raises(ValueError, match="at least one relay"):
        PowerSignal("PWR", Recorder(), [])


def test_events(relay_bank, tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    power = PowerSignal("PWR", rec, [relay_bank.resource("0")])
    power.on()
    power.outage(0.01)
    rec.stop_test()
    records = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()[1:]]
    assert [r["action"] for r in records] == ["on", "outage"]
    assert records[1]["requested_s"] == 0.01


def test_precise_sleep():
    start = clock.now()
    precise_sleep(0.01)
    assert 0.01 <= clock.now() - start < 0.11
