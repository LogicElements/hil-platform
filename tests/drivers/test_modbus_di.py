import pytest

from hil.comm import modbus
from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import DigitalInput


@pytest.fixture
def make_di(bus):
    def make(**options):
        options.setdefault("address", 5)
        options.setdefault("count", 8)
        device = create_device("di1", DeviceConfig(driver="modbus_di", bus="relay_bus", **options))
        device.bind({"relay_bus": bus})
        return device

    return make


def test_discrete_inputs_in_one_request(make_di, module):
    slave = module(5, ModbusDataStore(discrete_inputs={i: i in (1, 6) for i in range(8)}))
    di = make_di()
    di.open()
    count = len(slave.requests)
    assert di.read_all() == [False, True, False, False, False, False, True, False]
    assert slave.requests[count:] == [modbus.read_request(5, 2, 0, 8)]
    channel = di.resource("6")
    assert isinstance(channel, DigitalInput)
    assert channel.read() is True


def test_invert_and_start(make_di, module):
    module(5, ModbusDataStore(discrete_inputs={10 + i: i == 0 for i in range(4)}))
    di = make_di(count=4, start=10, invert=True)
    di.open()
    assert di.read_all() == [False, True, True, True]


def test_input_registers_hold_16_inputs_each(make_di, module):
    slave = module(5, ModbusDataStore(input_registers={0: 0b1000_0000_0000_0001, 1: 0b1}))
    di = make_di(count=20, source="input_registers")
    di.open()
    inputs = di.read_all()
    assert [i for i, on in enumerate(inputs) if on] == [0, 15, 16]
    assert slave.requests[-1] == modbus.read_request(5, 4, 0, 2)


def test_missing_input_module(make_di):
    with pytest.raises(DeviceNotFound, match="no answer from address 5 on bus 'relay_bus'"):
        make_di().open()


def test_read_requires_open(make_di):
    with pytest.raises(DeviceError, match="not open"):
        make_di().read(0)
