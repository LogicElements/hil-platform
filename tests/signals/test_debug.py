import json

import pytest

from hil.config.models import DebugParams, DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError, DeviceTimeout, OperationNotAllowed
from hil.recording import Recorder
from hil.signals import DebugSignal

TARGET = "target/stm32g4x.cfg"


@pytest.fixture
def probe():
    device = create_device("probe", DeviceConfig(driver="sim_probe", flash_s=0.05))
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
def swd(probe, recorder):
    signal = DebugSignal("SWD", recorder, probe)
    signal.configure("firmware", DebugParams(target=TARGET))
    return signal


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "fw.bin"
    path.write_bytes(b"\x01\x02")
    return path


def test_flash(swd, probe, image, tmp_path):
    result = swd.flash(image)
    assert result.ok and not result.interrupted
    assert probe.calls[-1][1:] == ("flash", TARGET, str(image))
    log = (tmp_path / "openocd.log").read_text(encoding="utf-8")
    assert "--- firmware: flash" in log
    assert "sim_probe flash" in log
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    assert (event["source"], event["action"], event["returncode"]) == ("SWD", "flash", 0)


def test_flash_interrupted(swd, image):
    result = swd.flash_interrupted(image, after_s=0.01)
    assert result.interrupted and result.returncode is None


def test_flash_interrupted_after_finish(swd, image):
    result = swd.flash_interrupted(image, after_s=1.0)
    assert result.ok and not result.interrupted


def test_reset_and_halt(swd, probe):
    swd.reset()
    swd.halt()
    assert [call[1] for call in probe.calls] == ["reset", "halt"]


def test_failure_is_device_error_with_log(swd, probe, image, tmp_path):
    probe.returncode = 1
    with pytest.raises(DeviceError, match="flash failed with exit code 1"):
        swd.flash(image)
    assert "sim_probe flash" in (tmp_path / "openocd.log").read_text(encoding="utf-8")


def test_timeout(probe, recorder, image):
    signal = DebugSignal("SWD", recorder, probe)
    signal.configure("firmware", DebugParams(target=TARGET, timeout_s=0.01))
    with pytest.raises(DeviceTimeout, match="did not finish"):
        signal.flash(image)


def test_missing_image(swd, tmp_path):
    with pytest.raises(FileNotFoundError, match="firmware image"):
        swd.flash(tmp_path / "missing.bin")


def test_target_needed(probe, recorder, image):
    signal = DebugSignal("SWD", recorder, probe)
    with pytest.raises(OperationNotAllowed, match="no debug target"):
        signal.flash(image)
    assert signal.flash(image, target="t.cfg").ok


def test_invalid_interrupt_time(swd, image):
    with pytest.raises(ValueError, match="after_s"):
        swd.flash_interrupted(image, after_s=0)
