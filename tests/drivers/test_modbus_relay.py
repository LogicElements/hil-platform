import pytest

from hil.comm import modbus
from hil.comm.slave import ModbusDataStore
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError, DeviceNotFound
from hil.resources import DigitalInput, RelayChannel


def coils(count=32, base=0, on=()):
    return {base + i: i in on for i in range(count)}


@pytest.fixture
def make_module(bus):
    def make(driver="waveshare_relay32", name="rel1", **options):
        options.setdefault("address", 1)
        device = create_device(name, DeviceConfig(driver=driver, bus="relay_bus", **options))
        device.bind({"relay_bus": bus})
        return device

    return make


def test_open_reads_initial_state(make_module, module):
    module(1, ModbusDataStore(coils=coils(on={3})))
    rel = make_module()
    rel.open()
    assert rel.initial_states[3] is True
    assert rel.states == rel.initial_states
    assert rel.get(3) is True


def test_set_many_is_one_frame(make_module, module):
    store = ModbusDataStore(coils=coils())
    slave = module(1, store)
    rel = make_module()
    rel.open()
    rel.set_many({2: True, 5: True})
    assert slave.requests[-1] == modbus.write_coils_request(1, 2, [True, False, False, True])
    assert [store.coils[i] for i in range(7)] == [False, False, True, False, False, True, False]
    assert rel.get(5) is True


def test_relay_channel(make_module, module):
    store = ModbusDataStore(coils=coils())
    module(1, store)
    rel = make_module()
    rel.open()
    channel = rel.resource("7")
    assert isinstance(channel, RelayChannel)
    channel.set(True)
    assert store.coils[7] is True
    assert channel.get() is True
    assert rel.read_back()[7] is True


def test_coil_base_and_single_writes(make_module, module):
    slave = module(1, ModbusDataStore(coils=coils(base=100)))
    rel = make_module(coil_base=100, write="single")
    rel.open()
    rel.set_many({1: True, 0: True})
    assert slave.requests[-2:] == [
        modbus.write_coil_request(1, 100, True),
        modbus.write_coil_request(1, 101, True),
    ]


def test_safe_state_switches_all_off_in_one_frame(make_module, module):
    store = ModbusDataStore(coils=coils(on=set(range(32))))
    slave = module(1, store)
    rel = make_module()
    rel.open()
    rel.safe_state()
    assert slave.requests[-1] == modbus.write_coils_request(1, 0, [False] * 32)
    assert not any(store.coils.values())


def test_missing_module_is_device_not_found(make_module):
    rel = make_module(address=9)
    with pytest.raises(DeviceNotFound, match="no answer from address 9 on bus 'relay_bus'"):
        rel.open()


def test_wrong_coil_map_is_device_error(make_module, module):
    module(1, ModbusDataStore(coils=coils(count=8)))
    with pytest.raises(DeviceError, match="illegal data address"):
        make_module().open()


def test_requires_open_and_valid_index(make_module):
    rel = make_module()
    with pytest.raises(DeviceError, match="not open"):
        rel.set_many({0: True})
    with pytest.raises(DeviceError, match="has no relay 32"):
        rel.set_many({32: True})


def test_bus_must_be_modbus_bus():
    rel = create_device("rel1", DeviceConfig(driver="waveshare_relay32", bus="x", address=1))
    assert rel.dependencies() == ["x"]
    other = create_device("x", DeviceConfig(driver="sim_relay"))
    with pytest.raises(ConfigError, match="'x' is not a modbus_rtu_bus"):
        rel.bind({"x": other})


def test_waveshare_and_quido_on_one_bus(make_module, module):
    waveshare = ModbusDataStore(coils=coils())
    quido = ModbusDataStore(coils=coils(), discrete_inputs={0: True, 1: False})
    module(1, waveshare, port="m1")
    module(2, quido, port="m2")
    rel1 = make_module()
    rel2 = make_module("quido_rs_2_32", name="rel2", address=2)
    rel1.open()
    rel2.open()
    rel1.set_many({0: True})
    rel2.set_many({31: True})
    assert waveshare.coils[0] is True and quido.coils[31] is True
    assert {"0", "31", "in0", "in1"} <= set(rel2.channel_names())
    in0 = rel2.resource("in0")
    assert isinstance(in0, DigitalInput)
    assert in0.read() is True
    assert rel2.resource("in1").read() is False


def test_quido_input_base(make_module, module):
    module(2, ModbusDataStore(coils=coils(), discrete_inputs={10: False, 11: True}))
    rel2 = make_module("quido_rs_2_32", name="rel2", address=2, input_base=10)
    rel2.open()
    assert rel2.read(1) is True
    with pytest.raises(DeviceError, match="has no input 2"):
        rel2.read(2)
