import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device, openocd
from hil.errors import DeviceError, DeviceNotFound, TerminationRequested
from hil.resources import DebugProbe

FAKE = Path(__file__).with_name("fake_openocd.py")


def make(**options):
    options.setdefault("command", [sys.executable, str(FAKE)])
    return create_device("stlink", DeviceConfig(driver="openocd", **options))


@pytest.fixture
def ocd():
    device = make(adapter_serial="066DFF", speed_khz=4000)
    device.open()
    yield device
    device.close()


def test_is_debug_probe():
    assert isinstance(make(), DebugProbe)


def test_arguments(ocd):
    args = ocd.arguments("target/stm32g4x.cfg", ["init", "halt"])
    assert args[1:] == [
        str(FAKE),
        "-f",
        "interface/stlink.cfg",
        "-c",
        "adapter serial 066DFF",
        "-f",
        "target/stm32g4x.cfg",
        "-c",
        "adapter speed 4000",
        "-c",
        "init",
        "-c",
        "halt",
    ]


def test_search_directories():
    device = make(search=["/opt/ocd/scripts"])
    device.open()
    assert device.arguments("t.cfg", [])[2:4] == ["-s", "/opt/ocd/scripts"]


def test_flash(ocd, tmp_path):
    image = tmp_path / "my fw.bin"
    image.write_bytes(b"\0")
    result = ocd.flash(image, "target/stm32g4x.cfg", timeout_s=10)
    assert result.ok and result.action == "flash"
    assert f"program {{{image.resolve().as_posix()}}} verify reset exit" in result.output
    assert "Programming Finished" in result.output


def test_reset_and_halt(ocd):
    reset = ocd.reset("t.cfg", timeout_s=10)
    assert reset.ok and "init | -c | reset run | -c | shutdown" in reset.output
    assert ocd.halt("t.cfg", timeout_s=10).ok


def test_failure_is_returned_with_output():
    device = make(adapter_serial="fail")
    device.open()
    result = device.reset("t.cfg", timeout_s=10)
    assert result.returncode == 1
    assert "simulated failure" in result.output


def test_timeout_and_abort(tmp_path):
    device = make(adapter_serial="slow")
    device.open()
    timed_out = device.reset("t.cfg", timeout_s=0.5)
    assert timed_out.timed_out and timed_out.returncode is None
    assert timed_out.duration_s < 5
    image = tmp_path / "fw.bin"
    image.write_bytes(b"\0")
    aborted = device.flash(image, "t.cfg", timeout_s=10, abort_after_s=0.3)
    assert aborted.interrupted and not aborted.timed_out


def test_missing_program():
    with pytest.raises(DeviceNotFound, match="OpenOCD program 'no-such-openocd' not found"):
        make(command=["no-such-openocd"]).open()


def test_requires_open():
    with pytest.raises(DeviceError, match="not open"):
        make().reset("t.cfg", timeout_s=1)


class InterruptedPopen(subprocess.Popen):
    """Popen whose first wait for the process is interrupted by a termination signal."""

    instances: ClassVar[list["InterruptedPopen"]] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stdin_arg = kwargs.get("stdin")
        self.calls = 0
        InterruptedPopen.instances.append(self)

    def communicate(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise TerminationRequested("SIGTERM")
        return super().communicate(*args, **kwargs)


def test_termination_during_run_kills_openocd(monkeypatch):
    InterruptedPopen.instances.clear()
    monkeypatch.setattr(openocd.subprocess, "Popen", InterruptedPopen)
    device = make(adapter_serial="slow")
    device.open()
    start = time.perf_counter()
    with pytest.raises(TerminationRequested):
        device.reset("t.cfg", timeout_s=30)
    assert time.perf_counter() - start < 5
    (process,) = InterruptedPopen.instances
    assert process.poll() is not None
    assert process.stdin_arg == subprocess.DEVNULL


class StuckPipePopen(subprocess.Popen):
    """Popen whose pipe stays open after the kill (a grandchild still holds it)."""

    def communicate(self, input=None, timeout=None):
        if timeout is None:
            raise AssertionError("unbounded wait for the killed process")
        if timeout < 1:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.wait()
        raise subprocess.TimeoutExpired(self.args, timeout)


def test_stuck_pipe_after_kill_does_not_hang(monkeypatch, caplog):
    monkeypatch.setattr(openocd.subprocess, "Popen", StuckPipePopen)
    device = make(adapter_serial="slow")
    device.open()
    result = device.reset("t.cfg", timeout_s=0.3)
    assert result.timed_out and result.returncode is None
    assert "did not close its output" in caplog.text
