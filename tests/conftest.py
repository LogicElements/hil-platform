import pytest

from hil.drivers.sim.relay import SimRelay, SimRelayConfig

pytest_plugins = ["pytester"]


@pytest.fixture
def relay_bank():
    bank = SimRelay("rel1", SimRelayConfig(channels=8))
    bank.open()
    yield bank
    bank.close()
