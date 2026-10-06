import logging
import os
import stat
from types import SimpleNamespace

import pytest

from hil.config.models import DeviceConfig, SerialParams
from hil.drivers import create_device
from hil.drivers.serial_ports import FtdiPort, ensure_low_latency, find_ftdi_port, resolve_port
from hil.errors import ConfigError, DeviceError, DeviceNotFound
from hil.resources import SerialLink


def make(**ports):
    return create_device("ft", DeviceConfig(driver="serial_ports", ports=ports))


def test_loop_url_port():
    device = make(A="loop://")
    device.open()
    link = device.resource("A")
    assert isinstance(link, SerialLink)
    with link.open(SerialParams(baud=921600), timeout=0.01) as port:
        port.write(b"abc")
        assert port.read(3) == b"abc"
        assert port.baudrate == 921600
    device.close()


def test_unknown_channel():
    with pytest.raises(ConfigError, match="no channel 'B'"):
        make(A="loop://").resource("B")


def test_open_port_requires_open_device():
    device = make(A="loop://")
    with pytest.raises(DeviceError, match="not open"):
        device.resource("A").open(SerialParams())


def test_port_that_cannot_be_opened_is_device_error(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    not_a_tty = tmp_path / "ttyUSB9"
    not_a_tty.mkdir()
    device = make(A=str(not_a_tty))
    device.open()
    with pytest.raises(DeviceError, match="cannot open port 'A'"):
        device.resource("A").open(SerialParams(), timeout=0.01)


def test_missing_port_linux(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    missing = str(tmp_path / "ttyUSB9")
    device = make(A="loop://", B=missing)
    with pytest.raises(DeviceNotFound, match=r"device 'ft': serial port 'B' not found: .*ttyUSB9"):
        device.open()


def test_missing_port_windows(monkeypatch):
    import hil.drivers.serial_ports

    calls = []

    def comports():
        calls.append(1)
        return PORTS

    monkeypatch.setattr(hil.drivers.serial_ports.list_ports, "comports", comports)
    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "win32")
    device = make(A="com7", B=r"\\.\COM5", C={"serial": "FT4ABC", "interface": 2})
    device.open()
    assert device._devices == {"A": "com7", "B": r"\\.\COM5", "C": "COM7"}
    assert len(calls) == 1
    device.close()
    with pytest.raises(DeviceNotFound, match="serial port 'D' not found: COM9"):
        make(A="COM7", D="COM9").open()


def test_ftdi_port_config():
    device = create_device(
        "ft",
        DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 2}}),
    )
    assert device.channel_names() == {"C"}
    with pytest.raises(ConfigError, match="interface"):
        create_device(
            "ft",
            DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 4}}),
        )


PORTS = [
    SimpleNamespace(device="/dev/ttyUSB0", serial_number="FT4ABC", location="1-1:1.0"),
    SimpleNamespace(device="/dev/ttyUSB2", serial_number="FT4ABC", location="1-1:1.2"),
    SimpleNamespace(device="COM7", serial_number="FT4ABCC", location=None),
    SimpleNamespace(device="COM5", serial_number="FT4ABCA", location=None),
]


def test_find_ftdi_port_linux():
    assert find_ftdi_port("FT4ABC", 2, PORTS, platform="linux") == "/dev/ttyUSB2"


def test_find_ftdi_port_windows():
    assert find_ftdi_port("FT4ABC", 2, PORTS, platform="win32") == "COM7"
    assert find_ftdi_port("FT4ABC", 0, PORTS, platform="win32") == "COM5"


def test_find_ftdi_port_missing():
    with pytest.raises(DeviceNotFound, match=r"FT4ABC.*interface 3"):
        find_ftdi_port("FT4ABC", 3, PORTS, platform="linux")


def fake_tty(tmp_path, value):
    tty = tmp_path / "dev" / "ttyUSB0"
    tty.parent.mkdir()
    tty.write_text("")
    sysfs = tmp_path / "sys"
    (sysfs / "ttyUSB0").mkdir(parents=True)
    latency = sysfs / "ttyUSB0" / "latency_timer"
    latency.write_text(f"{value}\n")
    return tty, sysfs, latency


def test_low_latency_is_set(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    ensure_low_latency(str(tty), sysfs, platform="linux")
    assert latency.read_text().strip() == "1"


def test_low_latency_untouched_when_set(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 1)
    os.chmod(latency, stat.S_IREAD)
    ensure_low_latency(str(tty), sysfs, platform="linux")
    assert latency.read_text().strip() == "1"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file permissions"
)
def test_low_latency_warns_without_permission(tmp_path, caplog):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    os.chmod(latency, stat.S_IREAD)
    with caplog.at_level(logging.WARNING, logger="hil.drivers.serial_ports"):
        ensure_low_latency(str(tty), sysfs, platform="linux")
    assert "latency timer" in caplog.text


def test_low_latency_ignores_other_platforms_and_urls(tmp_path):
    tty, sysfs, latency = fake_tty(tmp_path, 16)
    ensure_low_latency(str(tty), sysfs, platform="win32")
    ensure_low_latency("loop://", sysfs, platform="linux")
    assert latency.read_text().strip() == "16"


def test_open_resolves_ftdi_port(monkeypatch):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.list_ports, "comports", lambda: PORTS)
    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    device = create_device(
        "ft",
        DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 2}}),
    )
    device.open()
    assert device._devices == {"C": "/dev/ttyUSB2"}
    device.close()


def test_open_missing_ftdi_chip_raises(monkeypatch):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.list_ports, "comports", lambda: [])
    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")
    device = create_device(
        "ft",
        DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 2}}),
    )
    with pytest.raises(DeviceNotFound, match=r"FT4ABC.*interface 2"):
        device.open()


def test_open_comports_failure(monkeypatch):
    import hil.drivers.serial_ports

    def fail_comports():
        raise OSError("SetupAPI")

    monkeypatch.setattr(hil.drivers.serial_ports.list_ports, "comports", fail_comports)
    device = create_device(
        "ft",
        DeviceConfig(driver="serial_ports", ports={"C": {"serial": "FT4ABC", "interface": 2}}),
    )
    with pytest.raises(DeviceError, match="cannot list serial ports"):
        device.open()


def test_find_ftdi_single_port_chip_windows():
    ports = [SimpleNamespace(device="COM3", serial_number="A10K", location=None)]
    assert find_ftdi_port("A10K", 0, ports, platform="win32") == "COM3"
    with pytest.raises(DeviceNotFound):
        find_ftdi_port("A10K", 1, ports, platform="win32")


def test_find_ftdi_prefers_channel_suffix_windows():
    ports = [
        SimpleNamespace(device="COM3", serial_number="FT4ABC", location=None),
        SimpleNamespace(device="COM5", serial_number="FT4ABCA", location=None),
    ]
    assert find_ftdi_port("FT4ABC", 0, ports, platform="win32") == "COM5"


def test_resolve_port(monkeypatch, tmp_path):
    import hil.drivers.serial_ports

    monkeypatch.setattr(hil.drivers.serial_ports.sys, "platform", "linux")

    def comports():
        return PORTS

    assert resolve_port("bus", "port", "loop://", comports) == "loop://"
    ftdi = FtdiPort(serial="FT4ABC", interface=2)
    assert resolve_port("bus", "port", ftdi, comports) == "/dev/ttyUSB2"
    with pytest.raises(DeviceNotFound, match="device 'bus': serial port 'port' not found"):
        resolve_port("bus", "port", str(tmp_path / "missing"), comports)


def test_low_latency_checked_once_per_port(monkeypatch):
    import hil.drivers.serial_ports

    calls = []
    monkeypatch.setattr(hil.drivers.serial_ports, "ensure_low_latency", calls.append)
    device = make(A="loop://")
    device.open()
    for _ in range(3):
        device.resource("A").open(SerialParams(), timeout=0.01).close()
    assert calls == ["loop://"]
    device.close()
    device.open()
    device.resource("A").open(SerialParams(), timeout=0.01).close()
    assert calls == ["loop://", "loop://"]
    assert device.device_path("A") == "loop://"
    device.close()
