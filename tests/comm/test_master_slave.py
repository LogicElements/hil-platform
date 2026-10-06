import random
import struct
import threading
import time

import pytest
import serial

from hil.comm import modbus
from hil.comm import slave as slave_module
from hil.comm.framing import frame_length
from hil.comm.master import ModbusExceptionResponse, ModbusMaster, response_length
from hil.comm.slave import ModbusDataStore, ModbusSlave, request_length
from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceTimeout, TerminationRequested


@pytest.fixture
def bus():
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["master", "dut"]})
    )
    device.open()
    yield device
    device.close()


@pytest.fixture
def store():
    return ModbusDataStore(
        coils={0: False, 1: True, 2: False},
        discrete_inputs={0: True},
        holding_registers={0: 42, 1: 7},
        input_registers={5: 1234},
    )


@pytest.fixture
def slave(bus, store):
    with bus.endpoint("dut") as port, ModbusSlave(port, address=1, store=store) as slave:
        yield slave


@pytest.fixture
def master(bus):
    with bus.endpoint("master") as port:
        yield ModbusMaster(port, timeout_s=0.3)


def test_reads(master, slave):
    assert master.read_holding_registers(1, 0, 2) == [42, 7]
    assert master.read_input_registers(1, 5, 1) == [1234]
    assert master.read_coils(1, 0, 3) == [False, True, False]
    assert master.read_discrete_inputs(1, 0, 1) == [True]
    assert slave.requests[0] == modbus.read_request(1, 3, 0, 2)


def test_writes(master, slave, store):
    master.write_register(1, 1, 99)
    master.write_registers(1, 0, [5, 6])
    master.write_coil(1, 2, True)
    master.write_coils(1, 0, [True, True])
    assert store.holding_registers == {0: 5, 1: 6}
    assert store.coils == {0: True, 1: True, 2: True}


def test_exception_response(master, slave):
    with pytest.raises(ModbusExceptionResponse, match="illegal data address") as info:
        master.read_holding_registers(1, 10, 1)
    assert info.value.code == 2


def test_unknown_function_is_illegal(master, slave):
    with pytest.raises(ModbusExceptionResponse) as info:
        master.transact(modbus.request(1, 0x2B, b"\x0e\x01"))
    assert info.value.code == 1


def test_silent_slave_times_out(master, slave):
    slave.silent = True
    start = time.perf_counter()
    with pytest.raises(DeviceTimeout, match="no complete response"):
        master.read_holding_registers(1, 0, 1)
    assert 0.3 <= time.perf_counter() - start < 0.8


def test_other_address_times_out(master, slave):
    with pytest.raises(DeviceTimeout):
        master.read_holding_registers(2, 0, 1)


def test_broadcast_write(master, slave, store):
    assert master.transact(modbus.write_register_request(0, 0, 5)) is None
    deadline = time.perf_counter() + 1.0
    while store.holding_registers[0] != 5 and time.perf_counter() < deadline:
        time.sleep(0.005)
    assert store.holding_registers[0] == 5


def test_on_exchange(bus, slave):
    exchanges = []
    with bus.endpoint("master") as port:
        master = ModbusMaster(
            port, timeout_s=0.3, on_exchange=lambda q, r: exchanges.append((q, r))
        )
        master.read_holding_registers(1, 0, 1)
    request, response = exchanges[0]
    assert request == modbus.read_request(1, 3, 0, 1)
    assert modbus.decode(response).fields == {"values": [42]}


class FakePort:
    """Port that answers with prepared bytes."""

    def __init__(self, reply):
        self.timeout = 0.01
        self.reply = bytearray(reply)
        self.written = bytearray()

    @property
    def in_waiting(self):
        return len(self.reply)

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written += data
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        data = bytes(self.reply[:size])
        del self.reply[:size]
        return data


def test_echo_is_skipped():
    request = modbus.read_request(1, 3, 0, 1)
    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    master = ModbusMaster(FakePort(request + response), timeout_s=0.1, echo=True)
    assert master.read_holding_registers(1, 0, 1) == [9]


def test_bad_crc_response():
    response = bytearray(modbus.with_crc(bytes([1, 3, 2, 0, 9])))
    response[-1] ^= 0xFF
    with pytest.raises(DeviceError, match="bad CRC"):
        ModbusMaster(FakePort(response), timeout_s=0.1).read_holding_registers(1, 0, 1)


def test_response_from_other_device():
    response = modbus.with_crc(bytes([2, 3, 2, 0, 9]))
    with pytest.raises(DeviceError, match="from device 2"):
        ModbusMaster(FakePort(response), timeout_s=0.1).read_holding_registers(1, 0, 1)


def test_lengths():
    assert response_length(3, b"\x01") is None
    assert response_length(3, b"\x01\x03") is None
    assert response_length(3, b"\x01\x03\x04") == 9
    assert response_length(3, b"\x01\x83") == 5
    assert response_length(6, b"\x01\x06") == 8
    assert request_length(b"\x01\x03") == 8
    assert request_length(b"\x01\x10\x00\x00\x00\x02") is None
    assert request_length(b"\x01\x10\x00\x00\x00\x02\x04") == 13
    assert request_length(b"\x01\x2b") is None


def test_slave_rejects_bad_byte_count(store):
    slave = ModbusSlave(FakePort(b""), address=1, store=store)
    frame = modbus.request(1, 15, bytes.fromhex("00 00 00 03 02 05 00"))
    response = slave.respond(frame)
    assert response[1] == 0x8F
    assert response[2] == 3


@pytest.fixture
def slow_resync(monkeypatch):
    # only the fast resync can pass within the master's timeout, without tight timing
    monkeypatch.setattr(slave_module, "_RESYNC_S", 10.0)


def test_shared_bus_slaves_do_not_lose_requests(slow_resync):
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["master", "a", "b"]})
    )
    device.open()
    try:
        with (
            device.endpoint("a") as port_a,
            device.endpoint("b") as port_b,
            device.endpoint("master") as port_m,
            ModbusSlave(port_a, 1, ModbusDataStore(holding_registers={0: 11})),
            ModbusSlave(port_b, 2, ModbusDataStore(holding_registers={0: 22})),
        ):
            master = ModbusMaster(port_m, timeout_s=1.0)
            for _ in range(10):
                assert master.read_holding_registers(1, 0, 1) == [11]
                assert master.read_holding_registers(2, 0, 1) == [22]
    finally:
        device.close()


def test_slave_survives_internal_error(bus):
    store = ModbusDataStore(holding_registers={0: 70000, 1: 5})
    with bus.endpoint("dut") as port, ModbusSlave(port, 1, store), bus.endpoint("master") as port_m:
        master = ModbusMaster(port_m, timeout_s=0.3)
        with pytest.raises(ModbusExceptionResponse) as info:
            master.read_holding_registers(1, 0, 1)
        assert info.value.code == 4
        assert master.read_holding_registers(1, 1, 1) == [5]


def test_on_exchange_gets_received_bytes():
    exchanges = []
    exception = modbus.with_crc(bytes([1, 0x83, 2]))
    master = ModbusMaster(
        FakePort(exception), timeout_s=0.1, on_exchange=lambda q, r: exchanges.append(r)
    )
    with pytest.raises(ModbusExceptionResponse):
        master.read_holding_registers(1, 0, 1)
    assert exchanges == [exception]
    with pytest.raises(DeviceTimeout):
        master.read_holding_registers(1, 0, 1)
    assert exchanges[1] is None


def test_failing_on_exchange_does_not_hide_result(caplog):
    def broken(request, response):
        raise RuntimeError("callback failed")

    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    master = ModbusMaster(FakePort(response), timeout_s=0.1, on_exchange=broken)
    assert master.read_holding_registers(1, 0, 1) == [9]
    assert "on_exchange callback failed" in caplog.text


def test_echo_mismatch_is_reported_to_on_exchange():
    exchanges = []
    master = ModbusMaster(
        FakePort(b""), timeout_s=0.05, echo=True, on_exchange=lambda q, r: exchanges.append(r)
    )
    with pytest.raises(DeviceTimeout, match="echo"):
        master.read_holding_registers(1, 0, 1)
    assert exchanges == [b""]


def test_blocking_port_is_rejected():
    port = FakePort(b"")
    for timeout in (None, 0):
        port.timeout = timeout
        with pytest.raises(ValueError, match="timeout"):
            ModbusMaster(port)
        with pytest.raises(ValueError, match="timeout"):
            ModbusSlave(port, 1)


@pytest.fixture
def shared(slow_resync):
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["master", "a", "b"]})
    )
    device.open()
    stores = (
        ModbusDataStore(holding_registers={0: 11}),
        ModbusDataStore(holding_registers={i: 22 for i in range(120)}),
    )
    try:
        with (
            device.endpoint("a") as port_a,
            device.endpoint("b") as port_b,
            device.endpoint("master") as port_m,
            ModbusSlave(port_a, 1, stores[0]) as slave_a,
            ModbusSlave(port_b, 2, stores[1]),
        ):
            yield ModbusMaster(port_m, timeout_s=1.0), slave_a
    finally:
        device.close()


def test_overheard_large_response(shared):
    master, _ = shared
    for _ in range(10):
        assert master.read_holding_registers(2, 0, 120) == [22] * 120
        assert master.read_holding_registers(1, 0, 1) == [11]


def test_overheard_write_multiple_response(shared):
    master, _ = shared
    for _ in range(10):
        master.write_registers(2, 0, [5] * 96)
        assert master.read_holding_registers(1, 0, 1) == [11]


def test_requests_list_holds_only_requests(shared):
    master, slave = shared
    for _ in range(5):
        master.read_holding_registers(2, 0, 120)
        master.read_holding_registers(1, 0, 1)
    assert slave.requests
    for frame in slave.requests:
        assert request_length(frame) == len(frame)
    assert {frame[0] for frame in slave.requests} == {1, 2}


def test_request_with_crc_high_byte_zero_is_framed_whole():
    # the shortest CRC-valid prefix of such a request is its length minus one
    for seed in range(100_000):
        values = [bool(seed >> (bit % 17) & 1) for bit in range(40)]
        frame = modbus.write_coils_request(1, 0, values)
        if frame[-1] == 0:
            break
    else:
        pytest.fail("no request with a misleading CRC found")
    store = ModbusDataStore(coils={i: False for i in range(40)})
    slave = ModbusSlave(FakePort(b""), address=1, store=store)
    received = bytearray(frame[:-1])
    slave._frame(received)  # truncated: must wait for the last byte
    assert not slave.requests
    received += frame[-1:]
    slave._frame(received)
    assert slave.requests == [frame]
    assert not received


def test_broadcast_after_short_response_of_other_slave(shared):
    # a 7-byte FC3 response looks like the start of an 8-byte request; with the broadcast
    # address 0x00 appended its CRC is still valid
    master, slave = shared
    for k in range(10):
        assert master.read_holding_registers(2, 5, 1) == [22]
        master.write_register(0, 0, 100 + k)
        deadline = time.perf_counter() + 1.0
        while slave.store.holding_registers[0] != 100 + k and time.perf_counter() < deadline:
            time.sleep(0.002)
        assert slave.store.holding_registers[0] == 100 + k


def test_overheard_traffic_in_chunks_is_never_answered():
    rnd = random.Random(7)
    for i in range(400):
        store = ModbusDataStore(
            holding_registers={a: 0 for a in range(200)}, coils={a: False for a in range(2000)}
        )
        slave = ModbusSlave(FakePort(b""), 1, store)
        if i % 2:
            values = [rnd.choice((0, 1, 0x100, rnd.randrange(65536))) for _ in range(123)]
            frame = modbus.write_registers_request(2, 0, values[: rnd.randrange(1, 124)])
        else:
            bits = [rnd.random() < 0.5 for _ in range(rnd.randrange(1, 1969))]
            frame = modbus.write_coils_request(2, 0, bits)
        received = bytearray()
        pos = 0
        while pos < len(frame):
            size = rnd.randrange(1, 40)
            received += frame[pos : pos + size]
            pos += size
            slave._frame(received)
        assert not slave.port.written
        assert not any(store.coils.values()) and not any(store.holding_registers.values())
        assert all(request[0] == 2 for request in slave.requests)


def _own_request_with_early_crc_match():
    rnd = random.Random(3)
    for _ in range(100_000):
        values = [rnd.randrange(65536) for _ in range(rnd.randrange(1, 124))]
        frame = modbus.write_registers_request(1, 0, values)
        early = frame_length(frame)
        if early is not None and 7 < early < len(frame) - 1:
            return frame, early
    raise AssertionError("no request with an early CRC match found")


def _own_header_with_early_crc_match():
    # FC16 header whose first 6 bytes have a valid CRC: no length known yet
    for start in range(65536):
        for count in range(1, 124):
            if modbus.crc_ok(struct.pack(">BBHH", 1, 16, start, count)):
                return modbus.write_registers_request(1, start, [0] * count), 6
    raise AssertionError("no FC16 header with a valid CRC found")


@pytest.mark.parametrize(
    "make", [_own_request_with_early_crc_match, _own_header_with_early_crc_match]
)
@pytest.mark.parametrize("extra", [0, 1])
def test_own_request_with_early_crc_match_is_answered(make, extra):
    frame, early = make()
    start = struct.unpack(">H", frame[2:4])[0]
    count = struct.unpack(">H", frame[4:6])[0]
    store = ModbusDataStore(holding_registers={start + i: 0 for i in range(count)})
    slave = ModbusSlave(FakePort(b""), 1, store)
    received = bytearray(frame[: early + extra])
    slave._frame(received)
    assert not slave.port.written
    received += frame[early + extra :]
    slave._frame(received)
    assert slave.requests == [frame]
    assert bytes(slave.port.written) == modbus.with_crc(frame[:6])
    assert not received


def test_overheard_exception_response_is_not_recorded():
    slave = ModbusSlave(FakePort(b""), 1, ModbusDataStore())
    received = bytearray(modbus.with_crc(bytes([2, 0x83, 2])))
    slave._frame(received)
    assert not slave.requests
    assert not received
    assert not slave.port.written


def test_unknown_function_after_lone_zero_is_answered():
    # another slave's frame with CRC high byte 0x00 split before that byte leaves a lone
    # 0x00 at the buffer front; our next request has no known length
    other = next(
        frame
        for frame in (modbus.with_crc(bytes([2, 3, 2, i >> 8, i & 255])) for i in range(65536))
        if frame[-1] == 0 and frame[-2] != 0
    )
    request = modbus.request(1, 0x2B, bytes([0x0E, 1, 0]))
    slave = ModbusSlave(FakePort(b""), 1, ModbusDataStore())
    received = bytearray(other[:-1])
    slave._frame(received)
    received += other[-1:]
    slave._frame(received)
    received += request
    slave._frame(received)
    assert bytes(slave.port.written) == modbus.with_crc(bytes([1, 0xAB, 1]))
    assert slave.requests[-1] == request
    assert not received


def test_unknown_function_match_inside_overheard_frame_is_not_answered():
    # a CRC-valid "01 00 .." at the end of a partly received overheard frame is chance
    overheard = modbus.write_registers_request(2, 0, [0, 1, 0x100, 0, 0, 0])
    chance = modbus.with_crc(bytes([1, 0, 1]))
    slave = ModbusSlave(FakePort(b""), 1, ModbusDataStore())
    received = bytearray(overheard[:9] + chance)
    slave._frame(received)
    assert not slave.port.written
    assert not slave.requests


class EchoPort:
    """Half-duplex transceiver whose receiver hears the platform's own transmission."""

    def __init__(self):
        self.timeout = 0.01
        self.buffer = bytearray()
        self.cond = threading.Condition()
        self.written = []

    @property
    def in_waiting(self):
        with self.cond:
            return len(self.buffer)

    def reset_input_buffer(self):
        with self.cond:
            self.buffer.clear()

    def read(self, size=1):
        with self.cond:
            if not self.buffer:
                self.cond.wait(self.timeout)
            data = bytes(self.buffer[:size])
            del self.buffer[:size]
            return data

    def write(self, data):
        self.written.append(bytes(data))
        self.feed(data)
        return len(data)

    def feed(self, data):
        with self.cond:
            self.buffer += data
            self.cond.notify_all()


def test_slave_skips_its_own_echo():
    port = EchoPort()
    store = ModbusDataStore(holding_registers={0: 0})
    request = modbus.write_register_request(1, 0, 5)
    with ModbusSlave(port, 1, store, echo=True) as slave:
        port.feed(request)
        deadline = time.perf_counter() + 1.0
        while not port.written and time.perf_counter() < deadline:
            time.sleep(0.005)
        time.sleep(0.2)
    assert port.written == [request]
    assert slave.requests == [request]
    assert store.holding_registers[0] == 5


def test_slave_ignores_stale_input_at_start():
    port = EchoPort()
    port.feed(modbus.write_register_request(1, 0, 5))
    store = ModbusDataStore(holding_registers={0: 0})
    with ModbusSlave(port, 1, store, echo=True) as slave:
        time.sleep(0.1)
    assert not port.written
    assert not slave.requests


def test_master_port_error_is_device_error():
    port = FakePort(b"")

    def fail(data):
        raise serial.SerialException("port gone")

    port.write = fail
    with pytest.raises(DeviceError, match="port gone") as info:
        ModbusMaster(port, timeout_s=0.1).read_holding_registers(1, 0, 1)
    assert isinstance(info.value.__cause__, serial.SerialException)


def test_min_gap_between_requests(bus, slave):
    with bus.endpoint("master") as port:
        master = ModbusMaster(port, timeout_s=0.3, min_gap_s=0.05)
        master.read_holding_registers(1, 0, 1)
        start = time.perf_counter()
        master.read_holding_registers(1, 0, 1)
        assert time.perf_counter() - start >= 0.045


def test_min_gap_must_not_be_negative(bus):
    with bus.endpoint("master") as port, pytest.raises(ValueError, match="min_gap_s"):
        ModbusMaster(port, timeout_s=0.3, min_gap_s=-1)


def test_write_response_must_repeat_request(master, slave):
    slave.respond = lambda frame: modbus.with_crc(frame[:4] + b"\x00\x00")
    with pytest.raises(DeviceError, match="does not repeat the request"):
        master.write_register(1, 1, 99)


def test_multiple_write_response_must_match_start_and_count(master, slave):
    slave.respond = lambda frame: modbus.with_crc(frame[:2] + b"\x00\x00\x00\x01")
    with pytest.raises(DeviceError, match="does not match the start and count"):
        master.write_coils(1, 0, [True, False])


class InterruptedPort(FakePort):
    """Port whose first read is interrupted by a termination signal."""

    def __init__(self, reply):
        super().__init__(reply)
        self.interrupt = True
        self.write_times = []

    def write(self, data):
        self.write_times.append(time.perf_counter())
        return super().write(data)

    def read(self, size=1):
        if self.interrupt:
            self.interrupt = False
            raise TerminationRequested("SIGTERM")
        return super().read(size)


def test_interrupted_exchange_keeps_bus_quiet_until_its_deadline():
    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    port = InterruptedPort(response)
    master = ModbusMaster(port, timeout_s=0.3, min_gap_s=0.01)
    with pytest.raises(TerminationRequested):
        master.read_holding_registers(1, 0, 1)
    assert master.read_holding_registers(1, 0, 1) == [9]
    assert port.write_times[1] - port.write_times[0] >= 0.29


def test_completed_exchange_waits_only_min_gap():
    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    port = InterruptedPort(response + response)
    port.interrupt = False
    master = ModbusMaster(port, timeout_s=0.3, min_gap_s=0.01)
    master.read_holding_registers(1, 0, 1)
    master.read_holding_registers(1, 0, 1)
    assert port.write_times[1] - port.write_times[0] < 0.2


def test_exception_response_waits_only_min_gap():
    exception = modbus.with_crc(bytes([1, 0x83, 2]))
    response = modbus.with_crc(bytes([1, 3, 2, 0, 9]))
    port = InterruptedPort(exception + response)
    port.interrupt = False
    master = ModbusMaster(port, timeout_s=0.3, min_gap_s=0.01)
    with pytest.raises(ModbusExceptionResponse):
        master.read_holding_registers(1, 0, 1)
    assert master.read_holding_registers(1, 0, 1) == [9]
    assert port.write_times[1] - port.write_times[0] < 0.2
