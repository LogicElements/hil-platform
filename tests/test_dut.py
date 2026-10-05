from pathlib import Path

import pytest

from hil.config.loader import load_dut
from hil.dut import Dut
from hil.errors import SignalUnavailable
from hil.station import Station

EXAMPLE = Path(__file__).parents[1] / "examples" / "dut.yaml"


@pytest.fixture
def dut():
    with Station.from_files("sim") as station:
        yield Dut(load_dut(EXAMPLE, station.profile), station)


def test_signal_by_attribute(dut):
    assert dut.supply is dut.station.terminals["PWR"]
    dut.door_sensor.set(True)
    dut.alarm_out.wait_for(True, timeout=0.5)


def test_unwired_signal(dut):
    assert not dut.available("sensor_in3")
    with pytest.raises(SignalUnavailable, match=r"signal 'sensor_in3'.*'AO.1' is not wired"):
        dut.sensor_in3  # noqa: B018


def test_unknown_signal_is_attribute_error(dut):
    with pytest.raises(AttributeError, match="no signal 'door_sensr'"):
        dut.door_sensr  # noqa: B018
    with pytest.raises(AttributeError):
        dut.available("door_sensr")


def test_params(dut):
    assert dut.params("console") == {"baud": 115200}
    assert dut.params("supply") == {}
    assert dut.name == "example"
