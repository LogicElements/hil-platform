import time

import pytest
import serial

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.errors import DeviceError, WaitTimeout
from hil.recording import Recorder
from hil.signals import SerialSignal


@pytest.fixture
def ser():
    device = create_device(
        "ser", DeviceConfig(driver="sim_serial", buses={"con": ["con", "dut_con"]})
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
def console(ser, recorder):
    signal = SerialSignal("CON", recorder, ser.resource("con"))
    signal.configure("CON", SerialParams())
    yield signal
    signal.close()


@pytest.fixture
def dut_side(ser):
    with ser.endpoint("dut_con") as port:
        yield port


def test_expect(console, dut_side):
    dut_side.write(b"boot\r\nREADY 1.2\r\n")
    match = console.expect(r"READY (\S+)", timeout=1)
    assert match.group(1) == b"1.2"


def test_expect_consumes_output(console, dut_side):
    dut_side.write(b"tick\ntick\n")
    console.expect("tick", timeout=1)
    console.expect("tick", timeout=1)
    with pytest.raises(WaitTimeout):
        console.expect("tick", timeout=0.05)


def test_expect_timeout_shows_tail(console, dut_side):
    dut_side.write(b"booting...\n")
    start = time.perf_counter()
    with pytest.raises(WaitTimeout, match="READY") as info:
        console.expect("READY", timeout=0.1)
    assert 0.1 <= time.perf_counter() - start < 1.0
    assert "booting..." in str(info.value)


def test_write_reaches_dut(console, dut_side):
    console.write("help\n")
    assert dut_side.read(5) == b"help\n"


def test_read_until(console, dut_side):
    dut_side.write(b"a=1;b=2;")
    assert console.read_until(b";", timeout=1) == b"a=1;"
    assert console.read_until(b";", timeout=1) == b"b=2;"


def test_log_file(console, dut_side, tmp_path):
    dut_side.write(b"first\r\nsecond\r\n")
    console.expect("second", timeout=1)
    lines = (tmp_path / "serial-CON.log").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# start_utc")
    assert [line.split(maxsplit=1)[1] for line in lines[1:]] == ["first", "second"]


def test_configure_alias_and_settings(console, dut_side, tmp_path):
    console.configure("console", SerialParams(baud=9600))
    assert console.alias == "console"
    assert console.port.baudrate == 9600
    dut_side.write(b"x\n")
    console.expect("x", timeout=1)
    assert console.port.line_errors == 1
    assert (tmp_path / "serial-console.log").exists()


def test_safe_state_forgets_output(console, dut_side):
    dut_side.write(b"READY\n")
    deadline = time.perf_counter() + 1
    while b"READY" not in console._buffer and time.perf_counter() < deadline:
        time.sleep(0.005)
    console.safe_state()
    with pytest.raises(WaitTimeout):
        console.expect("READY", timeout=0.1)


def test_safe_state_drops_data_in_flight(console, tmp_path):
    generation = console._generation
    console.safe_state()
    console._received(b"LATE\n", generation)
    with pytest.raises(WaitTimeout):
        console.expect("LATE", timeout=0.05)
    assert "LATE" in (tmp_path / "serial-CON.log").read_text(encoding="utf-8")


def test_close_logs_partial_line(console, dut_side, tmp_path):
    dut_side.write(b"partial")
    deadline = time.perf_counter() + 1
    while b"partial" not in console._buffer and time.perf_counter() < deadline:
        time.sleep(0.005)
    console.close()
    assert "partial" in (tmp_path / "serial-CON.log").read_text(encoding="utf-8")


def test_port_failure_is_reported(console, ser):
    ser.close()
    time.sleep(0.05)
    with pytest.raises(DeviceError, match="serial port failed"):
        console.expect("anything", timeout=0.5)


def test_close(console):
    assert console.is_open
    console.close()
    assert not console.is_open


def test_safe_state_logs_partial_line(console, dut_side, tmp_path):
    dut_side.write(b"prompt> ")
    console.expect("prompt>", timeout=1)
    console.safe_state()
    assert "prompt>" in (tmp_path / "serial-CON.log").read_text(encoding="utf-8")


def test_write_failure_is_device_error(console, monkeypatch):
    def fail(data):
        raise serial.SerialException("write failed")

    monkeypatch.setattr(console.port, "write", fail)
    with pytest.raises(DeviceError, match="write failed") as info:
        console.write("x")
    assert isinstance(info.value.__cause__, serial.SerialException)


def test_safe_state_reopens_failed_port(console, ser):
    ser.close()
    time.sleep(0.05)
    with pytest.raises(DeviceError, match="serial port failed"):
        console.expect("anything", timeout=0.2)
    ser.open()
    console.safe_state()
    assert not console.is_open
    with ser.endpoint("dut_con") as side:
        console.open()
        side.write(b"back\n")
        console.expect("back", timeout=1)
