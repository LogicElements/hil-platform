import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device, driver_names, open_order
from hil.drivers.base import Device
from hil.drivers.sim.relay import SimRelay
from hil.errors import ConfigError


def test_builtin_sim_drivers_are_registered():
    assert {"sim_relay", "sim_di"} <= set(driver_names())


def test_create_device():
    device = create_device("rel1", DeviceConfig(driver="sim_relay", channels=4))
    assert isinstance(device, SimRelay)
    assert device.name == "rel1"


def test_unknown_driver():
    with pytest.raises(ConfigError, match=r"unknown driver 'nope'.*sim_relay"):
        create_device("x", DeviceConfig(driver="nope"))


def test_invalid_option():
    with pytest.raises(ConfigError, match="device 'x' \\(sim_relay\\): channels"):
        create_device("x", DeviceConfig(driver="sim_relay", channels=0))


def test_unknown_option():
    with pytest.raises(ConfigError, match="typo"):
        create_device("x", DeviceConfig(driver="sim_relay", typo=1))


def test_open_order_respects_dependencies():
    devices = {
        "di1": create_device("di1", DeviceConfig(driver="sim_di", mirror={0: "rel1.0"})),
        "rel1": create_device("rel1", DeviceConfig(driver="sim_relay")),
    }
    assert open_order(devices) == ["rel1", "di1"]


def test_open_order_unknown_dependency():
    devices = {"di1": create_device("di1", DeviceConfig(driver="sim_di", mirror={0: "rel9.0"}))}
    with pytest.raises(ConfigError, match="depends on unknown device 'rel9'"):
        open_order(devices)


class _Dependent(Device):
    def __init__(self, name, needs):
        super().__init__(name, Device.Config())
        self._needs = needs

    def dependencies(self):
        return self._needs


def test_open_order_cycle():
    devices = {"a": _Dependent("a", ["b"]), "b": _Dependent("b", ["a"])}
    with pytest.raises(ConfigError, match="cycle"):
        open_order(devices)
