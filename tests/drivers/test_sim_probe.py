from pathlib import Path

import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import DeviceError
from hil.resources import DebugProbe


@pytest.fixture
def probe():
    device = create_device("probe", DeviceConfig(driver="sim_probe", flash_s=0.05))
    device.open()
    yield device
    device.close()


def test_is_debug_probe(probe):
    assert isinstance(probe, DebugProbe)


def test_flash_records_call(probe):
    result = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=1)
    assert result.ok and result.action == "flash"
    assert result.duration_s >= 0.04
    assert probe.calls[-1][1:] == ("flash", "t.cfg", "fw.bin")


def test_abort_and_timeout(probe):
    aborted = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=1, abort_after_s=0.01)
    assert aborted.interrupted and not aborted.timed_out and aborted.returncode is None
    timed_out = probe.flash(Path("fw.bin"), "t.cfg", timeout_s=0.01)
    assert timed_out.timed_out and not timed_out.interrupted


def test_failure_and_closed(probe):
    probe.returncode = 3
    assert probe.reset("t.cfg", timeout_s=1).returncode == 3
    probe.fail_with = DeviceError("probe unplugged")
    with pytest.raises(DeviceError, match="unplugged"):
        probe.halt("t.cfg", timeout_s=1)
    probe.close()
    probe.fail_with = None
    with pytest.raises(DeviceError, match="not open"):
        probe.reset("t.cfg", timeout_s=1)
