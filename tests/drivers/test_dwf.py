import pytest

from hil.drivers import dwf
from hil.errors import DeviceError, DeviceNotFound, DeviceTimeout
from hil.resources import Waveform


@pytest.fixture
def lib(fake_dwf):
    return dwf.DwfLibrary()


def test_default_library(lib, fake_dwf):
    assert fake_dwf.loaded == [dwf.default_library()]
    assert dwf.default_library() in ("dwf.dll", "libdwf.so")


def test_missing_library(monkeypatch):
    def load(name):
        raise OSError("cannot open shared object file")

    monkeypatch.setattr(dwf, "_load", load)
    with pytest.raises(DeviceNotFound, match=r"'libdwf-x.so' cannot be loaded.*install WaveForms"):
        dwf.DwfLibrary("libdwf-x.so")


def test_devices(lib, fake_dwf):
    fake_dwf.devices.append(["SN:210415BXYZ", "Analog Discovery 3", True])
    assert lib.devices() == [
        dwf.DwfDeviceInfo(0, "210415BABCDE", "Analog Discovery 3", False),
        dwf.DwfDeviceInfo(1, "210415BXYZ", "Analog Discovery 3", True),
    ]


def test_failed_call_reports_last_error(lib, fake_dwf):
    fake_dwf.fail["FDwfDeviceOpen"] = "Device is busy"
    with pytest.raises(DeviceError, match="FDwfDeviceOpen failed: Device is busy"):
        lib.open(0)


def test_open_shuts_down_on_close(lib, fake_dwf):
    handle = lib.open(0)
    assert handle in fake_dwf.handles
    assert fake_dwf.params == {dwf.PARAM_ON_CLOSE: dwf.ON_CLOSE_SHUTDOWN}
    names = fake_dwf.names()
    assert names.index("FDwfParamSet") < names.index("FDwfDeviceOpen")
    lib.close(handle)
    assert fake_dwf.handles == set()


def test_open_disables_auto_configure(lib, fake_dwf):
    handle = lib.open(0)
    assert fake_dwf.auto_configure == 0
    assert fake_dwf.calls[-1] == ("FDwfDeviceAutoConfigureSet", (handle, 0))


def test_open_closes_device_when_auto_configure_fails(lib, fake_dwf):
    fake_dwf.fail["FDwfDeviceAutoConfigureSet"] = "USB error"
    with pytest.raises(DeviceError, match="USB error"):
        lib.open(0)
    assert fake_dwf.handles == set()


NODE_SETTERS = {
    "FDwfAnalogOutNodeEnableSet",
    "FDwfAnalogOutNodeFunctionSet",
    "FDwfAnalogOutNodeFrequencySet",
    "FDwfAnalogOutNodeAmplitudeSet",
    "FDwfAnalogOutNodeOffsetSet",
    "FDwfAnalogOutNodeSymmetrySet",
    "FDwfAnalogOutIdleSet",
}


def test_waveform_change_on_running_generator_is_applied_at_once(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 1, Waveform.dc(3.0))
    lib.awg_start(handle, 1)
    fake_dwf.calls.clear()
    lib.awg_apply(handle, 1, Waveform.sine(1000, 0.5, 0.5))
    names = fake_dwf.names()
    assert set(names[:-1]) == NODE_SETTERS
    assert fake_dwf.calls[-1] == ("FDwfAnalogOutConfigure", (handle, 1, dwf.AWG_APPLY))
    assert fake_dwf.running[1]


def test_waveform_change_on_stopped_generator_waits_for_start(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 0, Waveform.dc(1.0))
    lib.awg_start(handle, 0)
    lib.awg_stop(handle, 0)
    fake_dwf.calls.clear()
    lib.awg_apply(handle, 0, Waveform.dc(2.0))
    lib.awg_apply(handle, 1, Waveform.dc(2.0))
    assert "FDwfAnalogOutConfigure" not in fake_dwf.names()
    lib.awg_start(handle, 0)
    assert fake_dwf.calls[-1] == ("FDwfAnalogOutConfigure", (handle, 0, dwf.AWG_START))


def test_closed_device_forgets_running_generators(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_start(handle, 0)
    lib.close(handle)
    fake_dwf.calls.clear()
    lib.awg_apply(handle, 0, Waveform.dc(1.0))
    assert "FDwfAnalogOutConfigure" not in fake_dwf.names()


@pytest.mark.parametrize(
    ("wave", "expected"),
    [
        (Waveform.dc(-1.5), dwf.NodeSettings(dwf.FUNC_DC, 0.0, 0.0, -1.5, 50.0)),
        (Waveform.sine(1000, 2.0, 0.5), dwf.NodeSettings(dwf.FUNC_SINE, 1000.0, 2.0, 0.5, 50.0)),
        (
            Waveform.square(50, 1.0, duty=0.25),
            dwf.NodeSettings(dwf.FUNC_SQUARE, 50.0, 1.0, 0.0, 25.0),
        ),
        (
            Waveform.arbitrary([0.0, 2.0, 1.0, 0.0], rate=4000),
            dwf.NodeSettings(dwf.FUNC_CUSTOM, 1000.0, 1.0, 1.0, 50.0, (-1.0, 1.0, 0.0, -1.0)),
        ),
        (
            Waveform.arbitrary([3.0, 3.0], rate=10),
            dwf.NodeSettings(dwf.FUNC_CUSTOM, 5.0, 0.0, 3.0, 50.0, (0.0, 0.0)),
        ),
    ],
)
def test_node_settings(wave, expected):
    assert dwf.node_settings(wave) == expected


def test_awg_apply_and_start(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 1, Waveform.sine(1000, 2.0, 0.5))
    assert fake_dwf.out[1] == {
        "enabled": 1,
        "function": dwf.FUNC_SINE,
        "frequency": 1000.0,
        "amplitude": 2.0,
        "offset": 0.5,
        "symmetry": 50.0,
        "idle": dwf.IDLE_OFFSET,
    }
    lib.awg_start(handle, 1)
    assert fake_dwf.running[1]


def test_awg_arbitrary_data(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 0, Waveform.arbitrary([0.0, 2.0], rate=100))
    assert fake_dwf.out[0]["data"] == [-1.0, 1.0]


def test_awg_stop_goes_to_zero_volts(lib, fake_dwf):
    handle = lib.open(0)
    lib.awg_apply(handle, 0, Waveform.dc(3.0))
    lib.awg_start(handle, 0)
    lib.awg_stop(handle, 0)
    assert (fake_dwf.out[0]["function"], fake_dwf.out[0]["offset"]) == (dwf.FUNC_DC, 0.0)
    assert not fake_dwf.running[0]
    configures = [args for name, args in fake_dwf.calls if name == "FDwfAnalogOutConfigure"]
    # 0 V applied to the running generator before it stops
    assert configures[-2:] == [(handle, 0, dwf.AWG_APPLY), (handle, 0, dwf.AWG_STOP)]


def test_max_samples(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.awg_max = 4096
    fake_dwf.buffer_max = 16384
    assert lib.awg_max_samples(handle, 0) == 4096
    assert lib.scope_max_samples(handle) == 16384


def test_scope_setup(lib, fake_dwf):
    lib.scope_setup(lib.open(0), 50.0)
    assert fake_dwf.scope_range == {0: 50.0, 1: 50.0}


def test_scope_single(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.signal[1] = lambda i: i * 0.5
    data = lib.scope_acquire(handle, 1, 1000.0, 8, record=False, timeout_s=1.0)
    assert data.tolist() == [i * 0.5 for i in range(8)]
    assert ("FDwfAnalogInConfigure", (handle, 1, 1)) in fake_dwf.calls
    assert (fake_dwf.mode, fake_dwf.buffer_size, fake_dwf.rate) == (dwf.ACQ_SINGLE, 8, 1000.0)


def test_scope_single_timeout(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.polls_until_done = 10**9
    with pytest.raises(DeviceTimeout, match="did not finish"):
        lib.scope_acquire(handle, 0, 1000.0, 8, record=False, timeout_s=0.05)


def test_scope_record(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.record_chunk = 3000
    fake_dwf.signal[0] = float
    data = lib.scope_acquire(handle, 0, 100_000.0, 10_000, record=True, timeout_s=1.0)
    assert data.tolist() == [float(i) for i in range(10_000)]
    assert fake_dwf.mode == dwf.ACQ_RECORD
    assert fake_dwf.record_length == 0.0
    configures = [args for name, args in fake_dwf.calls if name == "FDwfAnalogInConfigure"]
    # reconfigure and start (the rate, mode and length take effect), then stop
    assert configures == [(handle, 1, 1), (handle, 0, 0)]


def test_scope_record_lost_samples(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.lost = 5
    with pytest.raises(DeviceError, match="lost 5"):
        lib.scope_acquire(handle, 0, 100_000.0, 10_000, record=True, timeout_s=1.0)
    assert fake_dwf.calls[-1] == ("FDwfAnalogInConfigure", (handle, 0, 0))


def test_scope_record_timeout(lib, fake_dwf):
    handle = lib.open(0)
    fake_dwf.record_chunk = 0
    with pytest.raises(DeviceTimeout, match="did not finish"):
        lib.scope_acquire(handle, 0, 1000.0, 100, record=True, timeout_s=0.05)


def test_rounded_rate_is_logged(lib, fake_dwf, caplog):
    handle = lib.open(0)
    fake_dwf.actual_rate = 99_000.0
    with caplog.at_level("WARNING", logger="hil.drivers.dwf"):
        lib.scope_acquire(handle, 0, 100_000.0, 8, record=False, timeout_s=1.0)
    assert "100000.0" in caplog.text
    assert "99000.0" in caplog.text


def test_exact_rate_logs_nothing(lib, fake_dwf, caplog):
    handle = lib.open(0)
    with caplog.at_level("WARNING", logger="hil.drivers.dwf"):
        lib.scope_acquire(handle, 0, 100_000.0, 8, record=False, timeout_s=1.0)
    assert caplog.text == ""
