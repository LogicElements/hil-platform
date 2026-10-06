"""Hardware checks of a real station; skipped unless HIL_HW_STATION names a station file.

    HIL_HW_STATION=stations/lab-a.yaml python -m pytest tests/hw -v

The wiring the checks need is described in doc/software/hw-testy.md.
"""

import os

import pytest

from hil.locking import StationLock
from hil.station import Station


@pytest.fixture(scope="session")
def hw_station():
    path = os.environ.get("HIL_HW_STATION", "")
    if not path:
        pytest.skip("set HIL_HW_STATION to run this hardware check")
    station = Station.from_files(path)
    with StationLock(station.name), station:
        yield station
