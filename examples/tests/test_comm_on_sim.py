"""Communication examples on the built-in simulated station.

The DUT side is played through ``hil.devices["ser"]``; on a real station the DUT
answers itself and these lines are left out.

    python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
"""

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import SerialParams


def test_console_ready(dut, hil):
    with hil.devices["ser"].endpoint("dut_con") as side:
        side.write(b"boot\r\nREADY\r\n")
        dut.console.expect(r"READY", timeout=1)


def test_modbus_register(dut, hil):
    dut.bus_monitor.start()
    params = SerialParams(baud=921600, parity="E")
    with (
        hil.devices["ser"].endpoint("dut_rs485", params) as side,
        ModbusSlave(side, address=1, store=ModbusDataStore(holding_registers={0: 7})),
    ):
        assert dut.rs485.modbus.read_holding_registers(1, 0, 1) == [7]
    dut.bus_monitor.wait_for_frame(
        lambda f: f.decoded is not None and f.decoded.kind == "response", timeout=1
    )
