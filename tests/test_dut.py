from pathlib import Path

import pytest

from hil.config.loader import load_dut
from hil.config.models import DebugParams
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


def test_unwired_signal(no_analog_station):
    with Station.from_files(no_analog_station) as station:
        dut = Dut(load_dut(EXAMPLE, station.profile), station)
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


def test_debug_signal_gets_target(tmp_path):
    path = tmp_path / "dut.yaml"
    path.write_text(
        "dut: d\nprofile: standard-v1\nsignals:\n"
        "  firmware: {terminal: SWD, target: target/stm32g4x.cfg, timeout_s: 30}\n",
        encoding="utf-8",
    )
    with Station.from_files("sim") as station:
        device = Dut(load_dut(path, station.profile), station)
        assert device.firmware.params == DebugParams(target="target/stm32g4x.cfg", timeout_s=30)
        assert device.firmware.alias == "firmware"
