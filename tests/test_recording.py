import json
from pathlib import Path

from hil.recording import Recorder


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_events_are_written_with_header(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path / "t1")
    rec.event("PWR", "on")
    rec.event("X1.1", "set", state=True)
    rec.stop_test()
    records = lines(tmp_path / "t1" / "events.jsonl")
    assert "start_utc" in records[0]
    assert records[1]["source"] == "PWR"
    assert records[1]["action"] == "on"
    assert records[1]["t"] >= 0
    assert records[2]["state"] is True


def test_records_without_test_are_dropped(tmp_path):
    rec = Recorder()
    rec.event("PWR", "on")
    assert rec.test_dir is None
    rec.start_test(tmp_path / "t1")
    rec.stop_test()
    rec.event("PWR", "off")
    assert not (tmp_path / "t1" / "events.jsonl").exists()


def test_non_json_values_are_stringified(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path)
    rec.write("custom.jsonl", {"path": Path("a")})
    rec.stop_test()
    assert lines(tmp_path / "custom.jsonl")[1] == {"path": "a"}


def test_next_test_gets_own_directory(tmp_path):
    rec = Recorder()
    rec.start_test(tmp_path / "a")
    rec.event("PWR", "on")
    rec.start_test(tmp_path / "b")
    rec.event("PWR", "off")
    rec.stop_test()
    assert lines(tmp_path / "a" / "events.jsonl")[1]["action"] == "on"
    assert lines(tmp_path / "b" / "events.jsonl")[1]["action"] == "off"
