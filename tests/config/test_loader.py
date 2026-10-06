from pathlib import Path

import pytest

from hil.config.loader import load_dut, load_profile, load_station, read_yaml
from hil.errors import ConfigError

STATION = """
name: t
profile: standard-v1
devices:
  rel1: {driver: sim_relay, channels: 8}
terminals:
  PWR: {kind: power, relays: [rel1.0, rel1.1]}
  X1.1: {kind: switch, relay: rel1.2}
"""

DUT = """
dut: d
profile: standard-v1
signals:
  supply: PWR
  door_sensor: X1.1
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_builtin_profile():
    profile = load_profile("standard-v1")
    assert profile.terminals["PWR"] == "power"
    assert profile.terminals["AO.1"] == "analog_out"


def test_profile_from_extra_dir_wins(tmp_path):
    write(tmp_path, "standard-v1.yaml", "profile: standard-v1\nterminals: {PWR: power}\n")
    assert list(load_profile("standard-v1", [tmp_path]).terminals) == ["PWR"]


def test_profile_name_must_match_file(tmp_path):
    write(tmp_path, "mine.yaml", "profile: other\nterminals: {PWR: power}\n")
    with pytest.raises(ConfigError, match=r"declares profile 'other'"):
        load_profile("mine", [tmp_path])


def test_unknown_profile():
    with pytest.raises(ConfigError, match=r"profile 'nope' not found"):
        load_profile("nope")


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read file"):
        read_yaml(tmp_path / "missing.yaml")


def test_empty_file(tmp_path):
    with pytest.raises(ConfigError, match="expected a mapping"):
        read_yaml(write(tmp_path, "empty.yaml", ""))


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        read_yaml(write(tmp_path, "bad.yaml", "a: [1, 2\n"))


def test_load_station(tmp_path):
    loaded = load_station(write(tmp_path, "s.yaml", STATION))
    assert loaded.config.name == "t"
    assert loaded.profile.profile == "standard-v1"
    assert loaded.source == tmp_path / "s.yaml"


def test_validation_error_names_file_and_field(tmp_path):
    path = write(tmp_path, "s.yaml", STATION.replace("relay: rel1.2", "relay: 5"))
    with pytest.raises(ConfigError) as info:
        load_station(path)
    message = str(info.value)
    assert str(path) in message
    assert "relay" in message
    assert "must be a string" in message


def test_reference_written_as_number(tmp_path):
    path = write(tmp_path, "s.yaml", STATION.replace("[rel1.0, rel1.1]", "[1.0, 1.1]"))
    with pytest.raises(ConfigError, match="must be a string"):
        load_station(path)


def test_terminal_not_in_profile(tmp_path):
    path = write(tmp_path, "s.yaml", STATION.replace("X1.1:", "X9.9:"))
    with pytest.raises(ConfigError, match=r"terminal 'X9.9' is not defined in profile"):
        load_station(path)


def test_terminal_kind_differs_from_profile(tmp_path):
    text = STATION.replace(
        "X1.1: {kind: switch, relay: rel1.2}", "X1.1: {kind: sense, input: rel1.2}"
    )
    with pytest.raises(
        ConfigError, match=r"has kind 'sense', profile 'standard-v1' defines 'switch'"
    ):
        load_station(write(tmp_path, "s.yaml", text))


def test_station_neither_file_nor_builtin():
    with pytest.raises(ConfigError, match="neither a file nor a built-in station"):
        load_station("no-such-station")


def test_load_dut(tmp_path):
    profile = load_profile("standard-v1")
    dut = load_dut(write(tmp_path, "dut.yaml", DUT), profile)
    assert dut.signals["door_sensor"].terminal == "X1.1"


def test_dut_profile_mismatch(tmp_path):
    profile = load_profile("standard-v1")
    path = write(tmp_path, "dut.yaml", DUT.replace("profile: standard-v1", "profile: other"))
    with pytest.raises(ConfigError, match=r"DUT uses profile 'other'"):
        load_dut(path, profile)


def test_dut_terminal_not_in_profile(tmp_path):
    profile = load_profile("standard-v1")
    path = write(tmp_path, "dut.yaml", DUT.replace("door_sensor: X1.1", "door_sensor: X7"))
    with pytest.raises(ConfigError, match=r"terminal 'X7', which is not in profile"):
        load_dut(path, profile)


def test_non_utf8_file(tmp_path):
    path = tmp_path / "cp1250.yaml"
    path.write_bytes("name: stanoviště\n".encode("cp1250"))
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        read_yaml(path)


def test_dut_serial_params(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, baud: 9600, parity: E}\n"
    dut = load_dut(write(tmp_path, "dut.yaml", text), profile)
    assert dut.signals["console"].params() == {"baud": 9600, "parity": "E"}


def test_dut_serial_param_typo(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, buad: 9600}\n"
    with pytest.raises(ConfigError, match=r"signal 'console': buad: Extra inputs"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)


def test_dut_invalid_parity(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON, parity: X}\n"
    with pytest.raises(ConfigError, match=r"signal 'console': parity"):
        load_dut(write(tmp_path, "dut.yaml", text), profile)


def test_params_on_signal_without_parameters(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT.replace("supply: PWR", "supply: {terminal: PWR, baud: 9600}")
    with pytest.raises(
        ConfigError, match=r"signal 'supply': terminal kind 'power' takes no parameters"
    ):
        load_dut(write(tmp_path, "dut.yaml", text), profile)


def test_dut_duplicate_port_terminal(tmp_path):
    profile = load_profile("standard-v1")
    text = DUT + "  console: {terminal: CON}\n  other: {terminal: CON}\n"
    with pytest.raises(
        ConfigError, match=r"signals 'console' and 'other' use the same serial terminal 'CON'"
    ):
        load_dut(write(tmp_path, "dut.yaml", text), profile)
