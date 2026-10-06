"""Example HIL tests, runnable on the built-in simulated station:

python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
"""

import pytest


def test_alarm_follows_door_sensor(dut):
    dut.supply.on()
    dut.door_sensor.set(True)
    t = dut.alarm_out.wait_for(True, timeout=0.5)
    assert t - dut.door_sensor.last_change < 0.050


def test_short_power_outage(dut):
    dut.supply.on()
    assert dut.supply.outage(0.1) >= 0.1


def test_rs485_link_cut_and_restore(dut):
    dut.supply.on()
    dut.link_ab_rs485.open()
    dut.link_ab_rs485.restore()


@pytest.mark.hil_requires("sensor_in3")
def test_analog_input(dut):
    # Skipped on stations without terminal AO.1.
    dut.sensor_in3.sine(freq=1000, amp=1.0)


@pytest.mark.hil_requires("sensor_out1")
def test_analog_output_measurement(dut):
    dut.supply.on()
    m = dut.sensor_out1.measure(duration_s=0.1)
    # On the "sim" station AI.1 reads the fixed input of sim_ad3 (1 V DC, 50 Hz sine 0.5 V).
    assert -24.0 <= m.dc <= 24.0
    assert m.rms_ac >= 0.0
