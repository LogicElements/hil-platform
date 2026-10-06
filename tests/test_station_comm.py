from pathlib import Path

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.loader import load_dut
from hil.config.models import SerialParams
from hil.dut import Dut
from hil.errors import ConfigError
from hil.signals import Rs485Monitor, Rs485Signal, SerialSignal
from hil.station import Station

EXAMPLE = Path(__file__).parents[1] / "examples" / "dut.yaml"


@pytest.fixture
def station():
    with Station.from_files("sim") as station:
        yield station


@pytest.fixture
def dut(station):
    return Dut(load_dut(EXAMPLE, station.profile), station)


def test_comm_terminals(station):
    assert isinstance(station.comm.serial("CON"), SerialSignal)
    assert isinstance(station.comm.serial("LOG"), SerialSignal)
    assert isinstance(station.comm.rs485("COM1"), Rs485Signal)
    assert isinstance(station.comm.monitor("MON1"), Rs485Monitor)
    with pytest.raises(ConfigError, match="is a rs485 terminal, not a serial"):
        station.comm.serial("COM1")


def test_dut_configures_and_opens_ports(dut, station):
    for terminal in ("CON", "LOG", "COM1", "MON1"):
        assert station.terminals[terminal].is_open
    assert dut.console.alias == "console"
    assert dut.console.params == SerialParams(baud=115200)
    assert dut.rs485.params == SerialParams(baud=921600, parity="E")
    assert dut.bus_monitor.alias == "bus_monitor"


def test_console_round_trip(dut, station):
    with station.devices["ser"].endpoint("dut_con") as side:
        side.write(b"boot\r\nREADY\r\n")
        dut.console.expect("READY", timeout=1)
        dut.console.write("status\n")
        assert side.read(7) == b"status\n"


def test_modbus_end_to_end(dut, station):
    dut.bus_monitor.start()
    params = SerialParams(baud=921600, parity="E")
    with (
        station.devices["ser"].endpoint("dut_rs485", params) as side,
        ModbusSlave(side, 1, ModbusDataStore(holding_registers={0: 3})),
    ):
        assert dut.rs485.modbus.read_holding_registers(1, 0, 1) == [3]
    frame = dut.bus_monitor.wait_for_frame(
        lambda f: f.decoded is not None and f.decoded.kind == "response", timeout=1
    )
    assert frame.decoded.fields["values"] == [3]


def test_safe_state_stops_monitor(station):
    monitor = station.comm.monitor("MON1")
    monitor.start()
    station.safe_state()
    assert not monitor.running


def test_close_releases_ports():
    station = Station.from_files("sim")
    station.open()
    console = station.comm.serial("CON")
    console.open()
    station.close()
    assert not console.is_open
