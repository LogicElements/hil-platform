import json
import time

import pytest
from serial import PortNotOpenError, SerialException

from hil.comm import modbus
from hil.comm.master import ModbusMaster
from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import (
    DeviceError,
    DeviceTimeout,
    OperationNotAllowed,
    ResourceConflict,
    WaitTimeout,
)
from hil.recording import Recorder
from hil.signals import Rs485Monitor, Rs485Signal

FRAME = modbus.read_request(1, 3, 0, 1)


def is_response(frame):
    return frame.decoded is not None and frame.decoded.kind == "response"


@pytest.fixture
def ser():
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"rs485": ["com1", "mon1", "dut"]})
    )
    device.open()
    yield device
    device.close()


@pytest.fixture
def recorder(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    yield rec
    rec.stop_test()


@pytest.fixture
def rs485(ser, recorder):
    signal = Rs485Signal("COM1", recorder, ser.resource("com1"))
    signal.configure("modbus", SerialParams(timeout_s=0.3))
    yield signal
    signal.close()


@pytest.fixture
def monitor(ser, recorder):
    signal = Rs485Monitor("MON1", recorder, ser.resource("mon1"))
    signal.configure("bus", SerialParams())
    signal.start()
    yield signal
    signal.close()


@pytest.fixture
def dut(ser):
    with ser.endpoint("dut") as port:
        yield port


def test_master_and_monitor(rs485, monitor, dut):
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 42})):
        assert rs485.modbus.read_holding_registers(1, 0, 1) == [42]
    request = monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    response = monitor.wait_for_frame(is_response, timeout=1)
    assert request.decoded.fields == {"start": 0, "count": 1}
    assert response.decoded.fields == {"values": [42]}
    assert response.t >= request.t


def test_platform_as_slave(rs485, dut):
    dut_master = ModbusMaster(dut, timeout_s=0.3)
    with rs485.slave(7, ModbusDataStore(holding_registers={3: 5})) as slave:
        assert dut_master.read_holding_registers(7, 3, 1) == [5]
        with pytest.raises(ResourceConflict):
            _ = rs485.modbus
        slave.silent = True
        with pytest.raises(DeviceTimeout):
            dut_master.read_holding_registers(7, 3, 1)
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 1})):
        assert rs485.modbus.read_holding_registers(1, 0, 1) == [1]


def test_inject_bad_crc(rs485, monitor, dut):
    sent = rs485.inject("bad_crc", FRAME)
    assert dut.read(len(sent)) == sent
    frame = monitor.wait_for_frame(lambda f: f.error is not None, timeout=1)
    assert frame.raw == sent


@pytest.mark.parametrize(("kind", "length"), [("truncated", 7), ("extended", 9)])
def test_inject_length_faults(rs485, dut, kind, length):
    sent = rs485.inject(kind, FRAME)
    assert len(sent) == length
    assert dut.read(length) == sent


def test_inject_bad_parity(rs485, dut):
    sent = rs485.inject("bad_parity", FRAME)
    assert sent == FRAME
    assert dut.read(len(FRAME)) == FRAME
    assert dut.line_errors == 1
    assert rs485.port.parity == "N"


def test_monitor_survives_garbage(rs485, monitor):
    rs485.send_raw(b"\x01\x02\x03")
    time.sleep(0.05)
    rs485.send_raw(FRAME)
    error = monitor.wait_for_frame(lambda f: f.error is not None, timeout=1)
    valid = monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    assert error.raw == b"\x01\x02\x03"
    assert valid.raw == FRAME
    assert monitor.running


def test_flood_runs_at_line_rate(rs485, dut):
    sent = rs485.flood(0.05, seed=1)
    limit = 0.05 / SerialParams().char_time_s() + 2 * 64
    assert 0.5 * 0.05 / SerialParams().char_time_s() <= sent <= limit
    assert dut.in_waiting == sent


def test_monitor_records_frames(rs485, monitor, tmp_path):
    rs485.send_raw(FRAME)
    monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    lines = (tmp_path / "rs485-bus.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["raw"] == FRAME.hex(" ")
    assert record["decoded"]["kind"] == "request"


def test_monitor_safe_state(rs485, monitor):
    rs485.send_raw(FRAME)
    monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    monitor.safe_state()
    assert monitor.frames == []
    assert not monitor.running
    with pytest.raises(OperationNotAllowed, match="start"):
        monitor.wait_for_frame(lambda f: True, timeout=0.1)


def test_master_exchange_is_recorded(rs485, dut, tmp_path):
    with ModbusSlave(dut, address=1, store=ModbusDataStore(holding_registers={0: 3})):
        rs485.modbus.read_holding_registers(1, 0, 1)
    events = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()[1:]]
    exchange = next(e for e in events if e["action"] == "modbus")
    assert exchange["request"] == FRAME.hex(" ")


def test_slave_blocks_other_operations(rs485):
    with rs485.slave(7):
        with pytest.raises(ResourceConflict):
            rs485.send_raw(FRAME)
        with pytest.raises(ResourceConflict):
            rs485.inject("bad_crc", FRAME)
        with pytest.raises(ResourceConflict):
            rs485.flood(0.01)
        with pytest.raises(ResourceConflict), rs485.slave(8):
            pass


def test_safe_state_and_close_stop_slave(rs485, dut):
    dut_master = ModbusMaster(dut, timeout_s=0.2)
    cm = rs485.slave(7, ModbusDataStore(holding_registers={3: 5}))
    thread = cm.__enter__()._thread
    assert dut_master.read_holding_registers(7, 3, 1) == [5]
    rs485.safe_state()
    assert not thread.is_alive()
    with pytest.raises(DeviceTimeout):
        dut_master.read_holding_registers(7, 3, 1)
    with rs485.slave(7) as slave:
        thread = slave._thread
    assert not thread.is_alive()
    cm = rs485.slave(7)
    thread = cm.__enter__()._thread
    rs485.close()
    assert not thread.is_alive()


def test_invalid_arguments(rs485):
    with pytest.raises(ValueError):
        rs485.inject("nonsense", FRAME)
    with pytest.raises(ValueError):
        rs485.flood(0)
    with pytest.raises(ValueError):
        rs485.flood(0.01, chunk=0)


def test_monitor_port_failure(ser, monitor):
    ser.close()
    with pytest.raises(DeviceError):
        monitor.wait_for_frame(lambda f: True, timeout=1)
    deadline = time.perf_counter() + 1.0
    while monitor.running and time.perf_counter() < deadline:
        time.sleep(0.005)
    assert not monitor.running


def test_slave_uses_echo_of_params(rs485):
    with rs485.slave(7) as slave:
        assert not slave.echo
    rs485.configure("modbus", SerialParams(timeout_s=0.3, echo=True))
    with rs485.slave(7) as slave:
        assert slave.echo


def test_port_errors_are_device_errors(rs485, monkeypatch):
    def fail(data):
        raise PortNotOpenError()

    monkeypatch.setattr(rs485.port, "write", fail)
    for action in (
        lambda: rs485.send_raw(FRAME),
        lambda: rs485.inject("bad_crc", FRAME),
        lambda: rs485.flood(0.01),
        lambda: rs485.modbus.read_holding_registers(1, 0, 1),
    ):
        with pytest.raises(DeviceError) as info:
            action()
        assert isinstance(info.value.__cause__, SerialException)


def test_bad_parity_waits_for_transmission(rs485, monkeypatch):
    import hil.signals.rs485

    sleeps = []
    monkeypatch.setattr(hil.signals.rs485.time, "sleep", sleeps.append)
    rs485.inject("bad_parity", FRAME)
    assert sleeps == [pytest.approx(len(FRAME) * rs485.params.char_time_s() + 0.002)]


def test_wait_after_stop_reports_stopped_monitor(rs485, monitor):
    rs485.send_raw(FRAME)
    monitor.wait_for_frame(lambda f: f.decoded is not None, timeout=1)
    monitor.stop()
    start = time.perf_counter()
    with pytest.raises(WaitTimeout, match="monitor is stopped; no matching frame among 1 captured"):
        monitor.wait_for_frame(lambda f: True, timeout=5)
    assert time.perf_counter() - start < 1


def test_close_closes_port_when_background_work_fails(rs485, monkeypatch):
    port = rs485.port

    def fail():
        raise RuntimeError("stop failed")

    monkeypatch.setattr(rs485, "_on_close", fail)
    with pytest.raises(RuntimeError):
        rs485.close()
    assert not port.is_open
    assert not rs485.is_open
