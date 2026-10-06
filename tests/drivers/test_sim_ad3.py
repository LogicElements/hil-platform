import math

import numpy as np
import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device
from hil.errors import ConfigError, DeviceError
from hil.resources import AwgChannel, ScopeChannel, Waveform


def make(**options):
    device = create_device("ad3", DeviceConfig(driver="sim_ad3", **options))
    device.open()
    return device


def test_channels():
    ad3 = make()
    assert set(ad3.channel_names()) == {"awg1", "awg2", "ch1", "ch2"}
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
