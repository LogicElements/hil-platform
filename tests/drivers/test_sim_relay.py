import pytest

from hil.drivers.sim.relay import SimRelay, SimRelayConfig
from hil.errors import ConfigError, DeviceError
from hil.resources import RelayChannel, set_relays


def test_set_requires_open():
    bank = SimRelay("r", SimRelayConfig(channels=4))
    with pytest.raises(DeviceError, match="not open"):
        bank.set_many({0: True})


def test_set_many_is_one_operation(relay_bank):
    relay_bank.set_many({0: True, 3: True})
    assert relay_bank.states[:4] == [True, False, False, True]
    assert len(relay_bank.history) == 1
    assert relay_bank.history[0][1] == {0: True, 3: True}


def test_resource(relay_bank):
    channel = relay_bank.resource("5")
    assert isinstance(channel, RelayChannel)
    channel.set(True)
    assert channel.get() is True
    assert str(channel) == "rel1.5"


@pytest.mark.parametrize("channel", ["8", "-1", "x"])
def test_resource_rejects_unknown_channel(relay_bank, channel):
    with pytest.raises(ConfigError, match=f"no channel '{channel}'"):
        relay_bank.resource(channel)


def test_resource_rejects_non_canonical_channel(relay_bank):
    with pytest.raises(ConfigError, match="no channel '05'"):
        relay_bank.resource("05")


def test_safe_state_switches_all_off(relay_bank):
    relay_bank.set_many({1: True, 2: True})
    relay_bank.safe_state()
    assert not any(relay_bank.states)


def test_fail_with(relay_bank):
    relay_bank.fail_with = DeviceError("boom")
    with pytest.raises(DeviceError, match="boom"):
        relay_bank.set_many({0: True})


def test_set_relays_groups_by_bank(relay_bank):
    other = SimRelay("rel2", SimRelayConfig(channels=4))
    other.open()
    set_relays(
        [
            (relay_bank.resource("0"), True),
            (other.resource("1"), True),
            (relay_bank.resource("1"), True),
        ]
    )
    assert relay_bank.history[-1][1] == {0: True, 1: True}
    assert len(relay_bank.history) == 1
    assert len(other.history) == 1
