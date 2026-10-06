"""A station on Modbus modules, with the modules simulated on the RS-485 line."""

import pytest

from hil.comm.slave import ModbusDataStore, ModbusSlave
from hil.config.models import SerialParams
from hil.drivers import register_driver
from hil.drivers.sim.serial_port import SimSerial
from hil.station import Station

BAUD = 115200


@register_driver("test_modbus_line")
class _ModbusLine(SimSerial):
    """sim_serial whose port m1 answers as relay module 1 and port m2 as input module 5."""

    def open(self):
        super().open()
        self.stores = {
            1: ModbusDataStore(coils={i: False for i in range(32)}),
            5: ModbusDataStore(discrete_inputs={i: False for i in range(8)}),
        }
        self._sides = [self.endpoint(p, SerialParams(baud=BAUD)) for p in ("m1", "m2")]
        self.slaves = [
            ModbusSlave(side, address, self.stores[address])
            for side, address in zip(self._sides, (1, 5), strict=True)
        ]
        for slave in self.slaves:
            slave.start()

    def close(self):
        for slave in getattr(self, "slaves", []):
            slave.stop()
        for side in getattr(self, "_sides", []):
            side.close()
        super().close()


STATION = f"""
name: modbus
profile: standard-v1
devices:
  line: {{driver: test_modbus_line, buses: {{relay: [bus, m1, m2]}}}}
  relay_bus: {{driver: modbus_rtu_bus, link: line.bus, baud: {BAUD}}}
  rel1: {{driver: waveshare_relay32, bus: relay_bus, address: 1}}
  di1: {{driver: modbus_di, bus: relay_bus, address: 5, count: 8}}
terminals:
  PWR: {{kind: power, relays: [rel1.0, rel1.1]}}
  X1.1: {{kind: switch, relay: rel1.2}}
  X2.1: {{kind: sense, input: di1.0}}
"""


@pytest.fixture
def station(tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text(STATION, encoding="utf-8")
    with Station.from_files(path) as station:
        yield station


def test_power_and_sense_over_modbus(station):
    coils = station.devices["line"].stores[1].coils
    inputs = station.devices["line"].stores[5].discrete_inputs
    station.power.on("PWR")
    assert coils[0] and coils[1]
    station.digital.set("X1.1", True)
    assert coils[2]
    inputs[0] = True
    assert station.digital.read("X2.1") is True
    station.safe_state()
    assert not any(coils.values())


def test_open_order_puts_the_bus_first(station):
    order = station._order
    assert order.index("line") < order.index("relay_bus") < order.index("rel1")
    assert order.index("relay_bus") < order.index("di1")
