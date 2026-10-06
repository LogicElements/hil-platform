import threading
import time

import pytest

from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.drivers.modbus_bus import ModbusRtuBus, find_bus
from hil.errors import ConfigError, DeviceError, DeviceNotFound, DeviceTimeout


def bus_device(**options):
    return create_device("b", DeviceConfig(driver="modbus_rtu_bus", **options))


def test_config_needs_exactly_one_port():
    with pytest.raises(ConfigError, match="exactly one of 'port' and 'link'"):
        bus_device()
    with pytest.raises(ConfigError, match="exactly one of 'port' and 'link'"):
        bus_device(port="loop://", link="ser.bus")


def test_default_gap():
    assert bus_device(port="loop://").config.gap_s() == pytest.approx(3.5 * 10 / 9600)
    assert bus_device(port="loop://", baud=115200).config.gap_s() == 0.002
    assert bus_device(port="loop://", min_gap_s=0.01).config.gap_s() == 0.01


def test_dependencies_and_link_type(line):
    assert bus_device(link="ser.bus").dependencies() == ["ser"]
    assert bus_device(port="loop://").dependencies() == []
    relay = create_device("rel", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match=r"link rel\.0 is not a serial port"):
        bus_device(link="rel.0").bind({"rel": relay})


def test_exchange_over_link(bus, module):
    module(1, ModbusDataStore(holding_registers={0: 5}))
    with bus.session() as master:
        assert master.read_holding_registers(1, 0, 1) == [5]
        assert master.min_gap_s == 0.002


def test_call_turns_modbus_exception_into_device_error(bus, module):
    module(1, ModbusDataStore())
    with pytest.raises(DeviceError, match=r"device 'rel1': .*illegal data address"):
        bus.call("rel1", lambda master: master.read_coils(1, 0, 1))


def test_session_requires_open(make_bus):
    bus = make_bus()
    with pytest.raises(DeviceError, match="not open"), bus.session():
        pass


def test_busy_bus_times_out(make_bus):
    bus = make_bus(lock_timeout_s=0.1)
    bus.open()
    holding = threading.Event()
    release = threading.Event()

    def hold():
        with bus.session():
            holding.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(1)
        start = time.perf_counter()
        with pytest.raises(DeviceTimeout, match="busy"), bus.session():
            pass
        assert time.perf_counter() - start < 1.0
    finally:
        release.set()
        thread.join()
        bus.close()


def test_own_port():
    bus = bus_device(port="loop://")
    bus.open()
    assert bus.is_open
    bus.close()
    assert not bus.is_open


def test_missing_own_port(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    bus = bus_device(port=str(tmp_path / "ttyUSB7"))
    with pytest.raises(DeviceNotFound, match="serial port 'port' not found"):
        bus.open()


def test_find_bus():
    bus = bus_device(port="loop://")
    assert isinstance(find_bus("rel1", "b", {"b": bus}), ModbusRtuBus)
    other = create_device("x", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match="device 'rel1': 'x' is not a modbus_rtu_bus"):
        find_bus("rel1", "x", {"x": other})
