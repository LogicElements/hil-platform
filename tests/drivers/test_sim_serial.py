import time

import pytest
from serial import SerialException

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError
from hil.resources import SerialLink

BUSES = {"con": ["con", "dut_con"], "bus": ["com1", "mon1", "dut"]}


@pytest.fixture
def ser():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    device.open()
    yield device
    device.close()


def test_pair_delivers_to_peer_only(ser):
    with ser.endpoint("con") as a, ser.endpoint("dut_con") as b:
        assert a.write(b"hello") == 5
        assert b.read(5) == b"hello"
        assert a.read(5) == b""


def test_bus_delivers_to_all_other_ports(ser):
    with ser.endpoint("com1") as com1, ser.endpoint("mon1") as mon1, ser.endpoint("dut") as dut:
        com1.write(b"\x01\x03")
        dut.write(b"\x01\x83")
        assert mon1.read(4) == b"\x01\x03\x01\x83"
        assert dut.read(2) == b"\x01\x03"
        assert com1.read(2) == b"\x01\x83"
        assert com1.in_waiting == 0


def test_read_timeout(ser):
    with ser.endpoint("con", timeout=0.05) as a:
        start = time.perf_counter()
        assert a.read(1) == b""
        assert time.perf_counter() - start >= 0.04


def test_line_settings_mismatch_counts_errors(ser):
    with ser.endpoint("con", SerialParams(baud=9600)) as slow, ser.endpoint("dut_con") as fast:
        slow.write(b"x")
        assert fast.read(1) == b"x"
        assert fast.line_errors == 1
        assert slow.line_errors == 0


def test_resource(ser):
    link = ser.resource("con")
    assert isinstance(link, SerialLink)
    assert str(link) == "ser.con"
    with pytest.raises(ConfigError, match="no channel 'nope'"):
        ser.resource("nope")


def test_port_already_open(ser):
    with ser.endpoint("con"), pytest.raises(DeviceError, match="already open"):
        ser.endpoint("con")


def test_open_port_requires_open_device():
    device = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    with pytest.raises(DeviceError, match="not open"):
        device.endpoint("con")


def test_closed_device_fails_port_io(ser):
    port = ser.endpoint("con")
    ser.close()
    with pytest.raises(SerialException):
        port.read(1)
    with pytest.raises(SerialException):
        port.write(b"x")


def test_two_devices_with_same_name_are_independent(ser):
    other = create_device("ser", DeviceConfig(driver="sim_serial", buses=BUSES))
    other.open()
    try:
        with ser.endpoint("con") as a, other.endpoint("dut_con") as b:
            a.write(b"x")
            assert b.read(1) == b""
    finally:
        other.close()


@pytest.mark.parametrize(
    ("buses", "message"),
    [
        ({"a": ["only"]}, "at least two ports"),
        ({"a": ["p", "q"], "b": ["q", "r"]}, "more than one bus"),
        ({"a": ["p.1", "q"]}, "invalid port name"),
        ({}, "at least 1"),
    ],
)
def test_config_validation(buses, message):
    with pytest.raises(ConfigError, match=message):
        create_device("ser", DeviceConfig(driver="sim_serial", buses=buses))
