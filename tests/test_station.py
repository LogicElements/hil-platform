import signal
import sys
import time

import pytest

from hil.drivers import register_driver
from hil.drivers.base import Device
from hil.drivers.sim.relay import SimRelay
from hil.errors import (
    ConfigError,
    DeviceError,
    DeviceNotFound,
    SignalUnavailable,
    TerminationRequested,
)
from hil.signals import FaultPath, PowerSignal, SenseSignal, SwitchSignal
from hil.station import Station

STATION = """
name: t
profile: standard-v1
devices:
  rel1: {driver: sim_relay, channels: 8}
  di1: {driver: sim_di, inputs: 2, mirror: {0: rel1.2}}
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  X1.1: {kind: switch, relay: rel1.2}
  X2.1: {kind: sense, input: di1.0}
  F1: {kind: fault_path, series: rel1.6, short: rel1.7}
"""


def make(tmp_path, text=STATION) -> Station:
    path = tmp_path / "station.yaml"
    path.write_text(text, encoding="utf-8")
    return Station.from_files(path)


@pytest.fixture
def station(tmp_path):
    with make(tmp_path) as station:
        yield station


def test_terminals_and_blocks(tmp_path):
    station = make(tmp_path)
    assert isinstance(station.terminals["PWR"], PowerSignal)
    assert isinstance(station.terminals["X1.1"], SwitchSignal)
    assert isinstance(station.terminals["X2.1"], SenseSignal)
    assert isinstance(station.terminals["F1"], FaultPath)
    assert list(station.power.signals) == ["PWR"]
    assert list(station.digital.switches) == ["X1.1"]
    assert list(station.digital.senses) == ["X2.1"]
    assert list(station.faults.paths) == ["F1"]


def test_unknown_channel(tmp_path):
    with pytest.raises(ConfigError, match=r"terminal 'X1.1'.*no channel '40'"):
        make(tmp_path, STATION.replace("relay: rel1.2", "relay: rel1.40"))


def test_wrong_resource_type(tmp_path):
    with pytest.raises(ConfigError, match=r"terminal 'X2.1': rel1.5 is not a DigitalInput"):
        make(tmp_path, STATION.replace("input: di1.0", "input: rel1.5"))


def test_terminal_lookup(tmp_path):
    station = make(tmp_path)
    assert station.terminal("PWR") is station.terminals["PWR"]
    with pytest.raises(SignalUnavailable, match=r"'AO.1' is not wired on station 't'"):
        station.terminal("AO.1")
    with pytest.raises(ConfigError, match="'NOPE' is not defined in profile"):
        station.terminal("NOPE")


def test_loopback(station):
    station.digital.set("X1.1", True)
    assert station.digital.wait_for("X2.1", True, timeout=0.5)


def test_safe_state(station):
    rel1 = station.devices["rel1"]
    station.power.on("PWR")
    station.digital.set("X1.1", True)
    station.faults.open("F1")
    station.safe_state()
    assert not any(rel1.states)
    assert station.faults["F1"].state == "ok"
    assert not station.power["PWR"].is_on


def test_safe_state_failure_is_reported(station):
    station.devices["rel1"].fail_with = DeviceError("bus down")
    with pytest.raises(DeviceError, match="safe state failed: bus down"):
        station.safe_state()
    station.devices["rel1"].fail_with = None


def test_close_is_idempotent(tmp_path):
    station = make(tmp_path)
    station.open()
    station.close()
    station.close()
    assert not station.devices["rel1"].is_open


@register_driver("test_failing_open")
class _FailingOpen(Device):
    def open(self):
        raise DeviceNotFound("not connected")


def test_open_failure_closes_opened_devices(tmp_path):
    # zz comes after rel1 in the open order, so rel1 is already open when zz fails
    text = STATION.replace("terminals:\n", "  zz: {driver: test_failing_open}\nterminals:\n")
    station = make(tmp_path, text)
    with pytest.raises(DeviceNotFound):
        station.open()
    assert station._order.index("rel1") < station._order.index("zz")
    assert not station.devices["rel1"].is_open
    assert station._opened == []


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def test_termination_signal_only_interrupts(station):
    previous = signal.getsignal(signal.SIGINT)
    station.install_emergency_handlers()
    station.power.on("PWR")
    handler = signal.getsignal(signal.SIGINT)
    with pytest.raises(TerminationRequested) as info:
        handler(signal.SIGINT, None)
    assert isinstance(info.value, KeyboardInterrupt)
    assert info.value.signame == "SIGINT"
    # no device I/O in the handler: the interrupted thread may be inside a bus frame
    assert station.devices["rel1"].states[0]
    assert handler(signal.SIGINT, None) is None  # a repeated signal is only logged
    station.close()
    assert not station.devices["rel1"].states[0]
    assert signal.getsignal(signal.SIGINT) is previous


@posix_only
def test_sigterm_interrupts(station):
    station.install_emergency_handlers()
    with pytest.raises(TerminationRequested, match="SIGTERM"):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)


@posix_only
def test_ignored_signal_stays_ignored(station):
    previous = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        station.install_emergency_handlers()
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        station.close()
        signal.signal(signal.SIGHUP, previous)


@register_driver("test_signal_in_safe_state")
class _SignalInSafeState(Device):
    """Delivers SIGINT to the station's handler while the safe state is being set."""

    armed = False

    def safe_state(self):
        if self.armed:
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)


def test_signal_during_close_does_not_abort_safe_state(tmp_path):
    text = STATION.replace(
        "terminals:\n", "  sig: {driver: test_signal_in_safe_state}\nterminals:\n"
    )
    station = make(tmp_path, text)
    station.open()
    station.install_emergency_handlers()
    station.devices["sig"].armed = True
    station.power.on("PWR")
    station.close()
    assert not station.devices["rel1"].states[0]


def test_at_exit_switches_power_off_despite_busy_recorder(station):
    station.power.on("PWR")
    station.recorder._lock.acquire()
    try:
        start = time.perf_counter()
        station._at_exit()
        elapsed = time.perf_counter() - start
    finally:
        station.recorder._lock.release()
    assert elapsed < 2.0
    assert not station.devices["rel1"].states[0]


def test_open_failure_keeps_original_exception(tmp_path):
    # rel2 has a terminal but comes after the failing device, so it is never opened
    text = (
        STATION.replace(
            "terminals:\n",
            "  mid: {driver: test_failing_open}\n  rel2: {driver: sim_relay, channels: 8}\nterminals:\n",
        )
        + "  X1.2: {kind: switch, relay: rel2.3}\n"
    )
    station = make(tmp_path, text)
    order = station._order
    assert order.index("rel1") < order.index("mid") < order.index("rel2")
    with pytest.raises(DeviceNotFound, match="not connected"):
        station.open()
    assert not station.devices["rel1"].is_open
    assert station._opened == []


def test_blocks_reject_typo_in_terminal_name(station):
    with pytest.raises(ConfigError, match="terminal 'PWRR' is not defined in the profile"):
        station.power["PWRR"]
    with pytest.raises(ConfigError, match=r"'X2.1' is a sense terminal, not a switch"):
        station.digital.switch("X2.1")
    with pytest.raises(ConfigError, match=r"'X1.1' is a switch terminal, not a sense"):
        station.digital.sense("X1.1")
    with pytest.raises(ConfigError, match="'PWR' is a power terminal, not a fault_path"):
        station.faults["PWR"]


def test_blocks_unwired_terminal_of_right_kind_is_unavailable(station):
    with pytest.raises(SignalUnavailable, match=r"no fault_path terminal 'F2'"):
        station.faults["F2"]
    with pytest.raises(SignalUnavailable, match=r"no switch terminal 'X1.2'"):
        station.digital.switch("X1.2")


@register_driver("test_bad_bind")
class _BadBind(Device):
    def bind(self, devices):
        raise ConfigError("depends on a missing device")


def test_bind_error_names_the_station_file(tmp_path):
    text = STATION.replace("terminals:\n", "  bad: {driver: test_bad_bind}\nterminals:\n")
    with pytest.raises(ConfigError, match=r"station\.yaml: depends on a missing device"):
        make(tmp_path, text)


def test_debug_terminal_needs_a_probe(tmp_path):
    with pytest.raises(ConfigError, match="device 'rel1' is not a debug probe"):
        make(tmp_path, STATION + "  SWD: {kind: debug, probe: rel1}\n")


def test_debug_block(tmp_path):
    text = STATION.replace("terminals:\n", "  probe: {driver: sim_probe}\nterminals:\n")
    with make(tmp_path, text + "  SWD: {kind: debug, probe: probe}\n") as station:
        assert station.debug.reset("SWD", "t.cfg").ok
        assert station.devices["probe"].calls[-1][1] == "reset"
        with pytest.raises(ConfigError, match="'PWR' is a power terminal, not a debug"):
            station.debug["PWR"]


@register_driver("test_missing_relay")
class _MissingRelay(SimRelay):
    def open(self):
        raise DeviceNotFound("relay module not connected")


BEST_EFFORT = (
    STATION.replace(
        "terminals:\n",
        "  bad: {driver: test_missing_relay, channels: 4}\n"
        "  di2: {driver: sim_di, inputs: 1, mirror: {0: bad.0}}\n"
        "terminals:\n",
    )
    + "  X1.2: {kind: switch, relay: bad.1}\n"
    + "  X2.2: {kind: sense, input: di2.0}\n"
)


def test_best_effort_open_sets_safe_state_on_the_rest(tmp_path):
    station = make(tmp_path, BEST_EFFORT)
    station.devices["rel1"].states[0] = True  # power left on, e.g. by a crashed run
    errors = station.open(best_effort=True)
    assert [str(e) for e in errors] == [
        "relay module not connected",
        "device 'di2' not opened: it depends on bad",
    ]
    assert station.devices["rel1"].is_open
    assert not station.devices["rel1"].states[0]
    assert not station.devices["di2"].is_open
    station.close()


def test_open_without_best_effort_fails_fast(tmp_path):
    station = make(tmp_path, BEST_EFFORT)
    with pytest.raises(DeviceNotFound, match="relay module not connected"):
        station.open()
    assert station._opened == []
