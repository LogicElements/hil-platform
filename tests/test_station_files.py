"""Station files in stations/ must stay valid; building a station does no I/O."""

from pathlib import Path

import pytest

from hil.cli import main
from hil.station import Station

STATIONS = sorted((Path(__file__).parents[1] / "stations").glob("*.yaml"))


def test_station_files_exist():
    assert STATIONS


@pytest.mark.parametrize("path", STATIONS, ids=lambda p: p.stem)
def test_station_file_is_valid(path, capsys):
    station = Station.from_files(path)
    assert station.name == path.stem
    if "bench" not in station.config.labels:  # bench stations wire only the device under bring-up
        assert "PWR" in station.terminals
    assert main(["check", "--station", str(path)]) == 0
    assert "configuration OK" in capsys.readouterr().out
