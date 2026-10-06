import pytest

from hil.config.models import DeviceConfig
from hil.drivers import create_device, driver_names, dwf
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import AwgChannel, ScopeChannel, Waveform
from hil.station import Station


def make(**options):
    return create_device(
        "ad3", DeviceConfig(driver="analog_discovery_3", scope_warmup_s=0, **options)
    )


def opened(**options):
    device = make(**options)
    device.open()
    return device


def test_registered_and_no_io_on_create(fake_dwf):
    assert "analog_discovery_3" in driver_names()
    make()
    assert fake_dwf.calls == []
    assert fake_dwf.loaded == []


def test_channels(fake_dwf):
    ad3 = make()
    assert set(ad3.channel_names()) == {"awg1", "awg2", "ch1", "ch2"}
    assert isinstance(ad3.resource("awg2"), AwgChannel)
    assert isinstance(ad3.resource("ch1"), ScopeChannel)


@pytest.mark.parametrize("serial", ["210415BABCDE", "SN:210415BABCDE", "210415babcde"])
def test_open_by_serial(fake_dwf, serial):
    fake_dwf.devices.insert(0, ["SN:OTHER", "Analog Discovery 2", False])
    opened(serial=serial)
    assert ("FDwfDeviceOpen", (1, "ref")) in fake_dwf.calls
    assert fake_dwf.scope_range == {0: 50.0, 1: 50.0}


def test_single_device_without_serial(fake_dwf):
    opened()
    assert fake_dwf.handles == {1}


def test_serial_not_found(fake_dwf):
    with pytest.raises(
        DeviceNotFound,
        match=r"serial 'NOPE' not found \(connected: 210415BABCDE \(Analog Discovery 3\)\)",
    ):
        opened(serial="NOPE")


def test_two_devices_need_serial(fake_dwf):
    fake_dwf.devices.append(["SN:210415BXYZ", "Analog Discovery 3", False])
    with pytest.raises(DeviceNotFound, match=r"2 WaveForms devices connected.*set 'serial'"):
        opened()


def test_no_device(fake_dwf):
    fake_dwf.devices.clear()
    with pytest.raises(DeviceNotFound, match="connected: none"):
        opened()


def test_device_in_use(fake_dwf):
    fake_dwf.devices[0][2] = True
    with pytest.raises(DeviceNotFound, match="used by another program"):
        opened()


def test_missing_library(monkeypatch):
    def load(name):
        raise OSError("not found")

    monkeypatch.setattr(dwf, "_load", load)
    with pytest.raises(DeviceNotFound, match="install WaveForms"):
        opened()


def test_library_option(fake_dwf):
    opened(library="/opt/dwf/libdwf.so")
    assert fake_dwf.loaded == ["/opt/dwf/libdwf.so"]


def test_open_failure_closes_device(fake_dwf):
    fake_dwf.fail["FDwfAnalogInConfigure"] = "USB error"
    with pytest.raises(DeviceError, match="USB error"):
        opened()
    assert fake_dwf.handles == set()


def test_second_open_releases_the_first_handle(fake_dwf):
    ad3 = opened()
    ad3.open()
    assert fake_dwf.handles == {2}
    ad3.close()
    assert fake_dwf.handles == set()


def test_interrupted_warmup_closes_device(fake_dwf, monkeypatch):
    def interrupted(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("hil.drivers.analog_discovery.time.sleep", interrupted)
    ad3 = make()
    with pytest.raises(KeyboardInterrupt):
        ad3.open()
    assert fake_dwf.handles == set()
    with pytest.raises(DeviceError, match="not open"):
        ad3.awg_start(0)


def test_generator(fake_dwf):
    awg = opened().resource("awg2")
    awg.sine(1000, 1.0)
    awg.start()
    assert fake_dwf.out[1]["function"] == dwf.FUNC_SINE
    assert fake_dwf.running[1]


def test_out_of_range_rejected(fake_dwf):
    ad3 = opened()
    fake_dwf.calls.clear()
    with pytest.raises(ValueError, match="exceeds the generator range"):
        ad3.awg_apply(0, Waveform.dc(5.5))
    assert fake_dwf.calls == []


def test_arbitrary_longer_than_buffer(fake_dwf):
    ad3 = opened()
    fake_dwf.awg_max = 4
    with pytest.raises(ValueError, match="5 samples exceed the generator buffer of 4"):
        ad3.awg_apply(0, Waveform.arbitrary([0.0] * 5, rate=100))
    assert "FDwfAnalogOutNodeFunctionSet" not in fake_dwf.names()


def test_scope_single_or_record(fake_dwf):
    ad3 = opened()
    fake_dwf.buffer_max = 100
    assert len(ad3.scope_acquire(0, 1000.0, 100)) == 100
    assert fake_dwf.mode == dwf.ACQ_SINGLE
    assert len(ad3.scope_acquire(0, 1000.0, 101)) == 101
    assert fake_dwf.mode == dwf.ACQ_RECORD


@pytest.mark.parametrize(("rate", "n"), [(0, 10), (1000, 0)])
def test_invalid_acquisition(fake_dwf, rate, n):
    with pytest.raises(ValueError):
        opened().scope_acquire(0, rate, n)


def test_safe_state_stops_both_generators(fake_dwf):
    ad3 = opened()
    for index in (0, 1):
        ad3.awg_apply(index, Waveform.dc(1.0))
        ad3.awg_start(index)
    ad3.safe_state()
    assert fake_dwf.running == {0: False, 1: False}
    assert [fake_dwf.out[i]["offset"] for i in (0, 1)] == [0.0, 0.0]


def test_safe_state_stops_second_generator_after_error(fake_dwf):
    ad3 = opened()
    stopped = []

    def awg_stop(handle, channel):
        if channel == 0:
            raise DeviceError("USB error")
        stopped.append(channel)

    ad3._lib.awg_stop = awg_stop
    with pytest.raises(DeviceError, match="awg1: USB error"):
        ad3.safe_state()
    assert stopped == [1]


def test_close(fake_dwf):
    ad3 = opened()
    ad3.close()
    assert fake_dwf.handles == set()
    with pytest.raises(DeviceError, match="not open"):
        ad3.awg_start(0)
    ad3.close()
    ad3.safe_state()


def test_station_does_not_load_the_library(fake_dwf, tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text(
        """
name: t
profile: standard-v1
devices:
  rel2: {driver: sim_relay, channels: 16}
  ad3: {driver: analog_discovery_3, serial: "210415BABCDE"}
analog:
  generators: [ad3.awg1, ad3.awg2]
terminals:
  AO.1: {kind: analog_out, select: rel2.0, connect: rel2.1}
  AI.1: {kind: analog_in, scope: ad3.ch1}
""",
        encoding="utf-8",
    )
    Station.from_files(path)
    assert fake_dwf.loaded == []
