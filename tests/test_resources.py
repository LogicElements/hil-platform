import math

import numpy as np
import pytest

from hil.drivers.sim.ad3 import SimAd3, SimAd3Config
from hil.resources import AwgChannel, ScopeChannel, Waveform


def test_dc():
    wave = Waveform.dc(-2.5)
    assert wave.kind == "dc"
    assert wave.peak_v == 2.5
    assert wave.describe() == {"kind": "dc", "volts": -2.5}


def test_sine():
    wave = Waveform.sine(1000, 1.5, offset=-1.0)
    assert (wave.frequency, wave.amplitude, wave.offset) == (1000.0, 1.5, -1.0)
    assert wave.peak_v == 2.5
    assert wave.describe() == {"kind": "sine", "freq": 1000.0, "amp": 1.5, "offset": -1.0}


def test_square():
    wave = Waveform.square(50, 2.0, duty=0.25)
    assert wave.duty == 0.25
    assert wave.describe()["duty"] == 0.25


def test_arbitrary_from_numpy():
    wave = Waveform.arbitrary(np.array([0.0, 1.0, -3.0]), rate=1000)
    assert wave.samples == (0.0, 1.0, -3.0)
    assert wave.peak_v == 3.0
    assert wave.describe() == {"kind": "arbitrary", "samples": 3, "rate": 1000.0}


@pytest.mark.parametrize(
    "make",
    [
        lambda: Waveform.sine(0, 1.0),
        lambda: Waveform.sine(-5, 1.0),
        lambda: Waveform.sine(math.inf, 1.0),
        lambda: Waveform.sine(100, -1.0),
        lambda: Waveform.square(100, 1.0, duty=0.0),
        lambda: Waveform.square(100, 1.0, duty=1.0),
        lambda: Waveform.dc(math.nan),
        lambda: Waveform.arbitrary([], rate=1000),
        lambda: Waveform.arbitrary([0.0, math.nan], rate=1000),
        lambda: Waveform.arbitrary([0.0], rate=0),
    ],
)
def test_invalid_waveforms(make):
    with pytest.raises(ValueError):
        make()


@pytest.fixture
def ad3():
    device = SimAd3("ad3", SimAd3Config())
    device.open()
    return device


def test_channels_delegate_to_the_device(ad3):
    awg = ad3.resource("awg2")
    assert isinstance(awg, AwgChannel)
    assert str(awg) == "ad3.awg2"
    awg.sine(1000, 1.0)
    awg.start()
    assert ad3.waves[1] == Waveform.sine(1000, 1.0)
    assert ad3.running == [False, True]
    awg.stop()
    assert ad3.running == [False, False]
    scope = ad3.resource("ch1")
    assert isinstance(scope, ScopeChannel)
    assert str(scope) == "ad3.ch1"
    assert len(scope.acquire(1000, 10)) == 10


def test_channels_are_hashable_and_compare_by_device_and_index(ad3):
    assert ad3.resource("awg1") == ad3.resource("awg1")
    assert ad3.resource("awg1") != ad3.resource("awg2")
    assert len({ad3.resource("ch1"), ad3.resource("ch1")}) == 1
