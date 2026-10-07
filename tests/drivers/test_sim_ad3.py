import math

import numpy as np
import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError
from hil.resources import AwgChannel, DigitalInput, LogicOutput, ScopeChannel, Waveform


def make(**options):
    device = create_device("ad3", DeviceConfig(driver="sim_ad3", **options))
    device.open()
    return device


def test_channels():
    ad3 = make()
    assert {"awg1", "awg2", "ch1", "ch2"} | {f"dio{i}" for i in range(16)} == set(
        ad3.channel_names()
    )
    assert isinstance(ad3.resource("awg1"), AwgChannel)
    assert isinstance(ad3.resource("ch2"), ScopeChannel)
    with pytest.raises(ConfigError, match="no channel 'awg3'"):
        ad3.resource("awg3")


def test_apply_start_stop_history():
    ad3 = make()
    wave = Waveform.dc(1.0)
    ad3.awg_apply(0, wave)
    ad3.awg_start(0)
    ad3.awg_stop(0)
    assert [(i, action) for _, i, action, _ in ad3.history] == [
        (0, "apply"),
        (0, "start"),
        (0, "stop"),
    ]
    assert ad3.history[0][3] == wave
    assert ad3.waves[0] is None
    assert ad3.running == [False, False]


def test_start_without_waveform():
    with pytest.raises(DeviceError, match="generator 2 has no waveform"):
        make().awg_start(1)


def test_generator_range():
    ad3 = make()
    with pytest.raises(ValueError, match=r"5.5 V exceeds the generator range"):
        ad3.awg_apply(0, Waveform.sine(100, 3.0, offset=2.5))
    assert ad3.waves == [None, None]


def test_closed_device():
    ad3 = make()
    ad3.close()
    with pytest.raises(DeviceError, match="not open"):
        ad3.awg_apply(0, Waveform.dc(0.0))
    with pytest.raises(DeviceError, match="not open"):
        ad3.scope_acquire(0, 1000, 10)


def test_fail_with():
    ad3 = make()
    ad3.fail_with = DeviceError("boom")
    with pytest.raises(DeviceError, match="boom"):
        ad3.scope_acquire(0, 1000, 10)


def test_scope_reads_configured_input():
    ad3 = make(inputs={"ch1": {"dc": 1.0, "sine": {"freq": 50, "amp": 0.5}}})
    data = ad3.scope_acquire(0, 100_000, 10_000)
    assert data.dtype == np.float64
    assert len(data) == 10_000
    assert float(np.mean(data)) == pytest.approx(1.0, abs=1e-9)
    assert float(np.std(data)) == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)
    assert ad3.acquisitions[-1][1:] == (0, 100_000, 10_000)
    assert float(np.max(np.abs(ad3.scope_acquire(1, 1000, 100)))) == 0.0


def test_noise_is_reproducible():
    a = make(inputs={"ch2": {"noise": 0.1}}, seed=3).scope_acquire(1, 1000, 100)
    b = make(inputs={"ch2": {"noise": 0.1}}, seed=3).scope_acquire(1, 1000, 100)
    assert np.array_equal(a, b)
    assert float(np.std(a)) > 0.05


def test_scope_clips_to_range():
    data = make(inputs={"ch1": {"dc": 40.0}}).scope_acquire(0, 1000, 10)
    assert float(np.max(data)) == 25.0


def test_set_input():
    ad3 = make()
    ad3.set_input("ch2", dc=-3.0, sine=(100, 1.0))
    data = ad3.scope_acquire(1, 10_000, 1000)
    assert float(np.mean(data)) == pytest.approx(-3.0, abs=1e-9)
    with pytest.raises(ValueError, match="no scope channel 'ch3'"):
        ad3.set_input("ch3", dc=1.0)


@pytest.mark.parametrize(("rate", "n"), [(0, 10), (1000, 0)])
def test_invalid_acquisition(rate, n):
    with pytest.raises(ValueError):
        make().scope_acquire(0, rate, n)


def test_safe_state_stops_both_generators():
    ad3 = make()
    for index in (0, 1):
        ad3.awg_apply(index, Waveform.dc(1.0))
        ad3.awg_start(index)
    ad3.safe_state()
    assert ad3.running == [False, False]
    assert ad3.waves == [None, None]


def test_dio_channels():
    ad3 = make(dio_outputs=[8])
    assert isinstance(ad3.resource("dio0"), DigitalInput)
    assert isinstance(ad3.resource("dio8"), LogicOutput)
    for bad in ("dio16", "dio08"):
        with pytest.raises(ConfigError, match=f"no channel '{bad}'"):
            ad3.resource(bad)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"dio_outputs": [16]}, "dio_outputs"),
        ({"dio_invert": [-1]}, "dio_invert"),
        ({"dio_outputs": [8, 8]}, "dio_outputs lists a line more than once"),
        ({"dio_outputs": [8], "dio_invert": [8]}, r"output lines \[8\] cannot be in dio_invert"),
        ({"dio_outputs": [8], "dio_loop": {0: 9}}, r"dio_loop: line 9 is not an output"),
        ({"dio_outputs": [8], "dio_loop": {8: 8}}, r"dio_loop: line 8 is an output"),
    ],
)
def test_dio_config_errors(options, message):
    with pytest.raises(ConfigError, match=message):
        make(**options)


def test_dio_inputs_and_invert():
    ad3 = make(dio_invert=[1])
    assert ad3.read(0) is False
    assert ad3.read(1) is True
    ad3.set_dio(0, True)
    ad3.set_dio(1, True)
    assert ad3.read(0) is True
    assert ad3.read(1) is False
    with pytest.raises(ValueError, match="line 8 is an output"):
        make(dio_outputs=[8]).set_dio(8, True)


@pytest.mark.parametrize("line", [-1, 16])
def test_set_dio_line_out_of_range(line):
    ad3 = make()
    with pytest.raises(ValueError, match=f"line {line} is out of range"):
        ad3.set_dio(line, True)
    assert ad3.dio_levels == [False] * 16


def test_dio_loop_and_output_level():
    ad3 = make(dio_outputs=[8], dio_loop={0: 8}, dio_invert=[0])
    assert ad3.read(0) is True  # released output reads 0, inverted
    ad3.drive(8, True)
    assert ad3.read(8) is True  # an output reads its own level, no inversion
    assert ad3.read(0) is False
    ad3.release(8)
    assert ad3.read(8) is False
    assert ad3.read(0) is True
    assert [(line, value) for _, line, value in ad3.dio_history] == [(8, True), (8, None)]


def test_drive_on_input_line():
    ad3 = make(dio_outputs=[8])
    with pytest.raises(DeviceError, match="line 3 is not an output"):
        ad3.drive(3, True)
    with pytest.raises(DeviceError, match="line 3 is not an output"):
        ad3.release(3)


def test_dio_closed_and_fail_with():
    ad3 = make(dio_outputs=[8])
    ad3.fail_with = DeviceError("boom")
    with pytest.raises(DeviceError, match="boom"):
        ad3.read(0)
    ad3.fail_with = None
    ad3.close()
    with pytest.raises(DeviceError, match="not open"):
        ad3.drive(8, True)


def test_safe_state_releases_dio_even_if_generators_fail():
    ad3 = make(dio_outputs=[8])
    ad3.drive(8, True)
    ad3.fail_with = DeviceError("boom")
    with pytest.raises(DeviceError, match="boom"):
        ad3.safe_state()
    assert ad3.dio_driven == {}
