import pytest
import yaml

from hil.config.loader import resolve_station_path
from hil.drivers.sim.relay import SimRelay, SimRelayConfig

pytest_plugins = ["pytester"]


@pytest.fixture
def relay_bank():
    bank = SimRelay("rel1", SimRelayConfig(channels=8))
    bank.open()
    yield bank
    bank.close()


@pytest.fixture
def no_analog_station(tmp_path):
    """The built-in station "sim" without analog terminals, for tests of unwired signals."""
    data = yaml.safe_load(resolve_station_path("sim").read_text(encoding="utf-8"))
    del data["analog"]
    data["terminals"] = {
        name: terminal
        for name, terminal in data["terminals"].items()
        if not name.startswith(("AO.", "AI."))
    }
    path = tmp_path / "sim-no-analog.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
