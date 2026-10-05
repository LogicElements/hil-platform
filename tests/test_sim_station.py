from hil.station import Station


def test_builtin_sim_station_loopback():
    with Station.from_files("sim") as station:
        assert station.name == "sim"
        station.digital.set("X1.1", True)
        station.digital.wait_for("X2.1", True, timeout=0.5)
        station.digital.set("X1.1", False)
        station.digital.wait_for("X2.1", False, timeout=0.5)
