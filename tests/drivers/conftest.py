import ctypes
from contextlib import ExitStack

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device, dwf

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


DWF_DONE, DWF_RUNNING = 2, 3


def _plain(arg):
    """Recorded form of a ctypes argument."""
    if hasattr(arg, "_obj"):
        return "ref"
    if isinstance(arg, ctypes.Array):
        return f"array[{len(arg)}]"
    return getattr(arg, "value", arg)


def _set(ref, value):
    ref._obj.value = value


class FakeDwf:
    """Stand-in for the WaveForms SDK library.

    Functions take ctypes arguments like the real library; outputs passed by
    reference are written through ``ref._obj``. Every call is recorded in ``calls``,
    a function named in ``fail`` returns 0 and sets the error message.
    """

    def __init__(self):
        # [serial as reported by FDwfEnumSN, device name, opened by another program]
        self.devices = [["SN:210415BABCDE", "Analog Discovery 3", False]]
        self.calls = []
        self.fail = {}
        self.error = ""
        self.loaded = []
        self.handles = set()
        self._next_handle = 1
        self.params = {}
        # value of FDwfDeviceAutoConfigureSet; 1 is the SDK default
        self.auto_configure = 1
        self.out = {0: {}, 1: {}}
        self.running = {0: False, 1: False}
        self.scope_range = {}
        # signal at the scope inputs: sample index -> volts
        self.signal = {0: lambda i: 1.0, 1: lambda i: -2.0}
        self.awg_max = 32768
        self.buffer_max = 32768
        self.rate = 0.0
        # rate reported by the device when it differs from the requested one
        self.actual_rate = None
        self.mode = 0
        self.buffer_size = 0
        self.record_length = 0.0
        self.record_chunk = 4096
        self.polls_until_done = 1
        self.lost = 0
        self._polls = 0
        self._recorded = 0

    def names(self):
        return [name for name, _ in self.calls]

    def __getattr__(self, name):
        if not name.startswith("FDwf"):
            raise AttributeError(name)
        handler = getattr(type(self), "_" + name[4:], None)
        if handler is None:
            raise AttributeError(f"fake dwf has no function {name}")

        def call(*args):
            self.calls.append((name, tuple(_plain(a) for a in args)))
            if name in self.fail:
                self.error = self.fail[name]
                return 0
            handler(self, *args)
            return 1

        return call

    def _GetLastErrorMsg(self, buf):
        buf.value = self.error.encode()

    def _Enum(self, enum_filter, count):
        _set(count, len(self.devices))

    def _EnumSN(self, index, buf):
        buf.value = self.devices[index.value][0].encode()

    def _EnumDeviceName(self, index, buf):
        buf.value = self.devices[index.value][1].encode()

    def _EnumDeviceIsOpened(self, index, used):
        _set(used, int(self.devices[index.value][2]))

    def _ParamSet(self, param, value):
        self.params[param.value] = value.value

    def _DeviceOpen(self, index, handle):
        self.handles.add(self._next_handle)
        _set(handle, self._next_handle)
        self._next_handle += 1

    def _DeviceAutoConfigureSet(self, handle, value):
        self.auto_configure = value.value

    def _DeviceClose(self, handle):
        self.handles.discard(handle.value)

    def _AnalogOutNodeEnableSet(self, handle, channel, node, enable):
        self.out[channel.value]["enabled"] = enable.value

    def _AnalogOutNodeFunctionSet(self, handle, channel, node, function):
        self.out[channel.value]["function"] = function.value

    def _AnalogOutNodeFrequencySet(self, handle, channel, node, hertz):
        self.out[channel.value]["frequency"] = hertz.value

    def _AnalogOutNodeAmplitudeSet(self, handle, channel, node, volts):
        self.out[channel.value]["amplitude"] = volts.value

    def _AnalogOutNodeOffsetSet(self, handle, channel, node, volts):
        self.out[channel.value]["offset"] = volts.value

    def _AnalogOutNodeSymmetrySet(self, handle, channel, node, percent):
        self.out[channel.value]["symmetry"] = percent.value

    def _AnalogOutNodeDataSet(self, handle, channel, node, data, count):
        self.out[channel.value]["data"] = list(data[: count.value])

    def _AnalogOutNodeDataInfo(self, handle, channel, node, low, high):
        _set(low, 2)
        _set(high, self.awg_max)

    def _AnalogOutIdleSet(self, handle, channel, idle):
        self.out[channel.value]["idle"] = idle.value

    def _AnalogOutConfigure(self, handle, channel, start):
        # 3 applies the settings and keeps the running state
        if start.value != 3:
            self.running[channel.value] = bool(start.value)

    def _AnalogInChannelEnableSet(self, handle, channel, enable):
        pass

    def _AnalogInChannelRangeSet(self, handle, channel, volts):
        self.scope_range[channel.value] = volts.value

    def _AnalogInChannelOffsetSet(self, handle, channel, volts):
        pass

    def _AnalogInBufferSizeInfo(self, handle, low, high):
        _set(low, 16)
        _set(high, self.buffer_max)

    def _AnalogInFrequencySet(self, handle, hertz):
        self.rate = hertz.value

    def _AnalogInFrequencyGet(self, handle, hertz):
        _set(hertz, self.rate if self.actual_rate is None else self.actual_rate)

    def _AnalogInAcquisitionModeSet(self, handle, mode):
        self.mode = mode.value

    def _AnalogInBufferSizeSet(self, handle, size):
        self.buffer_size = size.value

    def _AnalogInRecordLengthSet(self, handle, seconds):
        self.record_length = seconds.value

    def _AnalogInConfigure(self, handle, reconfigure, start):
        if start.value:
            self._polls = 0
            self._recorded = 0

    def _record_total(self):
        return round(self.record_length * self.rate)

    def _AnalogInStatus(self, handle, read_data, state):
        self._polls += 1
        if self.mode == 0:
            done = self._polls >= self.polls_until_done
        else:
            total = self._record_total()
            done = total > 0 and self._recorded >= total
        _set(state, DWF_DONE if done else DWF_RUNNING)

    def _AnalogInStatusRecord(self, handle, available, lost, corrupt):
        total = self._record_total()
        chunk = self.record_chunk if total == 0 else min(self.record_chunk, total - self._recorded)
        _set(available, chunk)
        _set(lost, self.lost)
        _set(corrupt, 0)

    def _AnalogInStatusData(self, handle, channel, buf, count):
        start = self._recorded if self.mode == 3 else 0
        for i in range(count.value):
            buf[i] = self.signal[channel.value](start + i)
        if self.mode == 3:
            self._recorded += count.value


@pytest.fixture
def fake_dwf(monkeypatch):
    fake = FakeDwf()

    def load(name):
        fake.loaded.append(name)
        return fake

    monkeypatch.setattr(dwf, "_load", load)
    return fake
