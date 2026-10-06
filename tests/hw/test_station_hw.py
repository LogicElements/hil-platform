"""Checks from "Co ověřit při stavbě" (doc/vyber/doporuceni.md) on a real station."""

import math
import os
import sys
import time
from pathlib import Path

import pytest

from hil.comm import modbus
from hil.config.models import SerialParams
from hil.drivers.analog_discovery import AnalogDiscovery3
from hil.drivers.modbus_relay import ModbusRelayModule
from hil.drivers.serial_ports import SYSFS_USB_SERIAL, SerialPorts
from hil.signals import measurement_of

pytestmark = pytest.mark.hw


def env(name):
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"set {name} to run this hardware check")
    return value


def require_flag(name):
    """Safety gate: the check runs only when the variable is exactly "1"."""
    if os.environ.get(name, "") != "1":
        pytest.skip(f"set {name}=1 to run this hardware check")


def relay_modules(station):
    modules = [d for d in station.devices.values() if isinstance(d, ModbusRelayModule)]
    if not modules:
        pytest.skip("the station has no Modbus relay modules")
    return modules


def test_relays_are_off_after_power_up(hw_station):
    """Run right after the relay modules were powered on (doporuceni.md, point 4)."""
    for module in relay_modules(hw_station):
        on = [i for i, state in enumerate(module.initial_states or []) if state]
        assert not on, f"{module.name}: relays {on} were on when the station opened"


def test_relay_coil_map(hw_station):
    """Every relay is switched alone and read back; needs HIL_HW_NO_DUT=1 (no DUT wired)."""
    require_flag("HIL_HW_NO_DUT")
    for module in relay_modules(hw_station):
        channels = module.config.channels
        for index in range(channels):
            module.set_many({index: True})
            assert module.read_back() == [i == index for i in range(channels)], index
            module.set_many({index: False})


def loopback_pairs():
    pairs = env("HIL_HW_LOOPBACK")  # e.g. "X1.1:X2.1,X1.2:X2.2"
    return [tuple(pair.split(":")) for pair in pairs.split(",")]


def test_loopback_latency_and_polling_period(hw_station):
    """Switch to sense through a loopback cable: latency and polling period (D-03)."""
    for switch_name, sense_name in loopback_pairs():
        switch = hw_station.digital.switch(switch_name)
        sense = hw_station.digital.sense(sense_name)
        for state in (True, False):
            switch.set(state)
            seen = sense.wait_for(state, timeout=0.5)
            latency = seen - switch.last_change
            print(f"{switch_name} -> {sense_name} {state}: {latency * 1000:.1f} ms")
            assert latency < 0.05
        with sense.record() as recording:
            time.sleep(0.5)
        print(f"{sense_name}: mean polling period {recording.mean_period_s * 1000:.2f} ms")


def test_outage_accuracy(hw_station):
    """PWR outage measured on a sense input wired to the DUT supply.

    The result includes the sampling resolution of the sense input (a sense read over the
    shared Modbus bus takes ~16-20 ms), so the tolerance is 10 ms plus the sampling period.
    """
    sense = hw_station.digital.sense(env("HIL_HW_SUPPLY_SENSE"))
    power = hw_station.power["PWR"]
    power.on()
    sense.wait_for(True, timeout=2)
    with sense.record(period_s=0.0005) as recording:
        reported = power.outage(0.1)
        time.sleep(0.2)
    power.off()
    offs = [t for t, state in recording.changes if not state]
    assert offs, "no off edge recorded"
    off = offs[0]
    ons = [t for t, state in recording.changes if state and t > off]
    assert ons, "no on edge after the off edge recorded"
    measured = ons[0] - off
    period = recording.mean_period_s
    print(
        f"outage 100 ms measured as {measured * 1000:.1f} ms, "
        f"power.outage returned {reported}, sampling period {period * 1000:.1f} ms"
    )
    assert abs(measured - 0.1) < 0.010 + period


@pytest.mark.skipif(sys.platform != "linux", reason="the latency timer is read from sysfs")
def test_ftdi_latency_timer(hw_station):
    ports = [d for d in hw_station.devices.values() if isinstance(d, SerialPorts)]
    if not ports:
        pytest.skip("the station has no serial_ports device")
    for device in ports:
        for channel in device.config.ports:
            device.resource(channel).open(SerialParams(), timeout=0.01).close()
            tty = Path(os.path.realpath(device.device_path(channel))).name
            timer = SYSFS_USB_SERIAL / tty / "latency_timer"
            if timer.exists():
                assert int(timer.read_text()) == 1, f"{device.name}.{channel}"


def test_rs485_monitor_sees_active_port(hw_station):
    """COM1 and MON1 on the same pair (HIL_HW_RS485_LOOP=1), 921 600 Bd, parity E."""
    require_flag("HIL_HW_RS485_LOOP")
    params = SerialParams(baud=921600, parity="E")
    port = hw_station.comm.rs485("COM1")
    monitor = hw_station.comm.monitor("MON1")
    port.configure("COM1", params)
    monitor.configure("MON1", params)
    monitor.start()
    frame = modbus.read_request(1, 3, 0, 1)
    port.send_raw(frame)
    seen = monitor.wait_for_frame(lambda f: f.raw == frame, timeout=1)
    assert seen.decoded is not None


def test_flash_with_openocd(hw_station):
    """Flash HIL_HW_IMAGE with OpenOCD target HIL_HW_TARGET through SWD."""
    target = env("HIL_HW_TARGET")
    image = env("HIL_HW_IMAGE")
    swd = hw_station.debug["SWD"]
    assert swd.flash(image, target).ok
    assert swd.reset(target).ok


def analog_discovery(station):
    devices = [d for d in station.devices.values() if isinstance(d, AnalogDiscovery3)]
    if not devices:
        pytest.skip("the station has no Analog Discovery 3")
    return devices[0]


@pytest.mark.parametrize(("generator", "scope"), [("awg1", "ch1"), ("awg2", "ch2")])
def test_ad3_generator_loopback(hw_station, generator, scope):
    """W1 wired to 1+, W2 to 2+, 1- and 2- to ground; needs HIL_HW_AD3_LOOP=1."""
    require_flag("HIL_HW_AD3_LOOP")
    ad3 = analog_discovery(hw_station)
    awg, channel = ad3.resource(generator), ad3.resource(scope)
    try:
        awg.dc(2.0)
        awg.start()
        time.sleep(0.1)
        m = measurement_of(channel.acquire(100_000, 10_000))
        print(f"{generator} DC 2 V -> {scope}: dc {m.dc:.4f} V, rms_ac {m.rms_ac:.4f} V")
        assert m.dc == pytest.approx(2.0, abs=0.1)
        awg.sine(1000, 1.0)
        time.sleep(0.1)
        m = measurement_of(channel.acquire(100_000, 10_000))
        print(f"{generator} sine 1 kHz 1 V -> {scope}: dc {m.dc:.4f} V, rms_ac {m.rms_ac:.4f} V")
        assert m.dc == pytest.approx(0.0, abs=0.1)
        assert m.rms_ac == pytest.approx(1 / math.sqrt(2), rel=0.05)
        long = channel.acquire(100_000, 200_000)  # more than the buffer: record mode
        assert len(long) == 200_000
        assert measurement_of(long).rms_ac == pytest.approx(1 / math.sqrt(2), rel=0.05)
    finally:
        awg.stop()


def analog_pairs():
    """HIL_HW_ANALOG_LOOP=AO.1:AI.1,AO.2:AI.3 - outputs wired to inputs by jumpers."""
    pairs = [tuple(pair.split(":")) for pair in env("HIL_HW_ANALOG_LOOP").split(",")]
    if len(pairs) > 2:
        pytest.fail("HIL_HW_ANALOG_LOOP takes at most 2 pairs (the station has 2 generators)")
    return pairs


def test_analog_multiplexer_loopback(hw_station):
    """Both generators through the output multiplexer, then the "no signal" state."""
    pairs = analog_pairs()
    analog = hw_station.analog
    # the second terminal gets generator 1, which is also wired to AO.0 without a relay:
    # distinct but non-negative levels, harmless to a DUT input left on AO.0
    levels = [1.5, 2.5]
    try:
        for (out, _), level in zip(pairs, levels, strict=False):
            analog.dc(out, level)
        for (out, inp), level in zip(pairs, levels, strict=False):
            m = analog.measure(inp)
            generator = analog.output(out).generator
            print(f"{out} ({generator}) {level} V -> {inp}: {m.dc:.4f} V")
            assert m.dc == pytest.approx(level, abs=0.1)
        analog.disconnect_all()
        for out, inp in pairs:
            m = analog.measure(inp)
            print(f"{out} disconnected -> {inp}: {m.dc:.4f} V")
            assert abs(m.dc) < 0.2
    finally:
        analog.disconnect_all()
