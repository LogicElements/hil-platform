import pytest

from hil.drivers.sim.di import SimDi, SimDiConfig
from hil.errors import ConfigError
from hil.resources import DigitalInput


def make(relay_bank, **options):
    di = SimDi("di1", SimDiConfig(**options))
    di.bind({"rel1": relay_bank, "di1": di})
    di.open()
    return di


def test_mirror_follows_relay(relay_bank):
    di = make(relay_bank, inputs=2, mirror={0: "rel1.2"})
    assert di.dependencies() == ["rel1"]
    sense = di.resource("0")
    assert isinstance(sense, DigitalInput)
    assert sense.read() is False
    relay_bank.resource("2").set(True)
    assert sense.read() is True


def test_set_value_for_unmirrored_input(relay_bank):
    di = make(relay_bank, inputs=2)
    di.set_value(1, True)
    assert di.resource("1").read() is True


def test_mirror_index_out_of_range(relay_bank):
    with pytest.raises(ConfigError, match="mirror input 5 is out of range"):
        make(relay_bank, inputs=2, mirror={5: "rel1.2"})


def test_mirror_must_be_relay(relay_bank):
    with pytest.raises(ConfigError, match="is not a relay"):
        make(relay_bank, inputs=2, mirror={0: "di1.1"})
