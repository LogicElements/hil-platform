import re
from pathlib import Path

import pytest

from hil.cli import main
from hil.locking import StationLock

EXAMPLE_DUT = Path(__file__).parents[1] / "examples" / "dut.yaml"


def test_check_builtin_station(capsys):
    assert main(["check", "--station", "sim"]) == 0
    assert "station 'sim': configuration OK" in capsys.readouterr().out


def test_check_with_dut_and_probe(capsys):
    assert main(["check", "--station", "sim", "--dut", str(EXAMPLE_DUT), "--probe"]) == 0
    out = capsys.readouterr().out
    assert "DUT 'example': 6 signals OK" in out
    assert "all 2 devices opened" in out


def test_info(capsys):
    assert main(["info", "--station", "sim"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"X1\.1\s+switch\s+wired", out)
    assert re.search(r"AO\.1\s+analog_out\s+not wired", out)
    assert re.search(r"rel1\s+sim_relay", out)
    assert re.search(r"power\s+PWR", out)


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
