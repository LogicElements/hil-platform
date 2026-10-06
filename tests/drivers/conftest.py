from contextlib import ExitStack

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device

BAUD = 115200


@pytest.fixture
def line():
    """Simulated RS-485 line: the bus driver on port 'bus', modules on 'm1' to 'm3'."""
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"relay": ["bus", "m1", "m2", "m3"]})
    )
    device.open()
    yield device
    device.close()


@pytest.fixture
def make_bus(line):
    def make(**options):
        options.setdefault("timeout_s", 0.2)
        bus = create_device(
            "relay_bus",
            DeviceConfig(driver="modbus_rtu_bus", link="ser.bus", baud=BAUD, **options),
        )
        bus.bind({"ser": line})
        return bus

    return make


@pytest.fixture
def bus(make_bus):
    device = make_bus()
    device.open()
    yield device
    device.close()


@pytest.fixture
def module(line):
    """Start a simulated Modbus module: ``module(address, store, port="m1")``."""
    with ExitStack() as stack:

        def start(address: int, store: ModbusDataStore, port: str = "m1") -> ModbusSlave:
            side = stack.enter_context(line.endpoint(port, SerialParams(baud=BAUD)))
            return stack.enter_context(ModbusSlave(side, address, store))

        yield start
