import re
from pathlib import Path

import pytest

from hil.cli import main
from hil.drivers import register_driver
from hil.drivers.base import Device
from hil.errors import DeviceNotFound
from hil.locking import StationLock

EXAMPLE_DUT = Path(__file__).parents[1] / "examples" / "dut.yaml"


def test_check_builtin_station(capsys):
    assert main(["check", "--station", "sim"]) == 0
    assert "station 'sim': configuration OK" in capsys.readouterr().out


def test_check_with_dut_and_probe(capsys):
    assert main(["check", "--station", "sim", "--dut", str(EXAMPLE_DUT), "--probe"]) == 0
    out = capsys.readouterr().out
    assert "DUT 'example': 11 signals OK" in out
    assert "all 6 devices opened" in out


def test_info(capsys):
    assert main(["info", "--station", "sim"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"X1\.1\s+switch\s+wired", out)
    assert re.search(r"AO\.1\s+analog_out\s+wired", out)
    assert re.search(r"analog\s+AO\.0, AO\.1, AO\.2, AO\.3, AO\.4, AI\.1, AI\.2, AI\.3, AI\.4", out)
    assert re.search(r"rel1\s+sim_relay", out)
    assert re.search(r"power\s+PWR", out)
    assert re.search(r"comm\s+CON, LOG, COM1, MON1", out)
    assert re.search(r"CON\s+serial\s+wired", out)
    assert re.search(r"SWD\s+debug\s+wired", out)
    assert re.search(r"debug\s+SWD", out)


def test_safe(capsys):
    assert main(["safe", "--station", "sim"]) == 0
    assert "safe state set" in capsys.readouterr().out


def test_config_error_exit_code(tmp_path, capsys):
    path = tmp_path / "s.yaml"
    path.write_text("name: s\nprofile: standard-v1\ndevices: {r: {driver: nope}}\nterminals: {}\n")
    assert main(["check", "--station", str(path)]) == 2
    assert "unknown driver 'nope'" in capsys.readouterr().err


def test_locked_station_exit_code(capsys):
    with StationLock("sim"):
        assert main(["safe", "--station", "sim"]) == 3
    assert "used by another process" in capsys.readouterr().err


def test_command_is_required():
    with pytest.raises(SystemExit):
        main([])


@register_driver("test_cli_missing")
class _Missing(Device):
    def open(self):
        raise DeviceNotFound("module not connected")


def test_safe_is_best_effort(tmp_path, capsys):
    path = tmp_path / "s.yaml"
    path.write_text(
        "name: cli-best-effort\nprofile: standard-v1\ndevices:\n"
        "  rel1: {driver: sim_relay}\n  gone: {driver: test_cli_missing}\n"
        "terminals:\n  PWR: {kind: power, relays: [rel1.0, rel1.1]}\n",
        encoding="utf-8",
    )
    assert main(["safe", "--station", str(path)]) == 3
    err = capsys.readouterr().err
    assert err.count("device error: module not connected") == 1
    assert "safe state set only on the devices that opened" in err


_events: list[str] = []


@register_driver("test_cli_tracked")
class _Tracked(Device):
    def open(self):
        _events.append(f"open {self.name}")

    def safe_state(self):
        _events.append(f"safe {self.name}")

    def close(self):
        _events.append(f"close {self.name}")


@register_driver("test_cli_interrupted")
class _Interrupted(Device):
    def open(self):
        raise KeyboardInterrupt


def test_safe_interrupted_during_open_still_closes(tmp_path):
    _events.clear()
    path = tmp_path / "s.yaml"
    path.write_text(
        "name: cli-interrupted\nprofile: standard-v1\ndevices:\n"
        "  first: {driver: test_cli_tracked}\n  stuck: {driver: test_cli_interrupted}\n"
        "terminals: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyboardInterrupt):
        main(["safe", "--station", str(path)])
    assert _events == ["open first", "safe first", "close first"]
