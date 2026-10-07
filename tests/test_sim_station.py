import math

import pytest

from hil.station import Station


def test_builtin_sim_station_loopback():
    with Station.from_files("sim") as station:
        assert station.name == "sim"
        station.digital.set("X1.1", True)
        station.digital.wait_for("X2.1", True, timeout=0.5)
        station.digital.set("X1.1", False)
        station.digital.wait_for("X2.1", False, timeout=0.5)


def test_builtin_sim_station_analog():
    with Station.from_files("sim") as station:
        station.analog.sine("AO.1", 1000, 1.0)
        m = station.analog.measure("AI.1", 0.02)
        assert m.dc == pytest.approx(1.0, abs=1e-6)
        assert m.rms_ac == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
        assert station.analog.measure("AI.3", 0.02).dc == pytest.approx(12.0)


def test_builtin_sim_station_logic_out_loopback():
    with Station.from_files("sim") as station:
        out = station.digital.logic_out("X3.1")
        out.set(True)
        station.digital.wait_for("X2.8", True, timeout=0.5)
        out.set(False)
        station.digital.wait_for("X2.8", False, timeout=0.5)
        out.set(True)
        ad3 = station.devices["ad3"]
    # closing the station released the output
    assert ad3.dio_driven == {}
