import pytest

from hil.locking import StationLock, StationLocked


def test_second_lock_fails(tmp_path):
    first = StationLock("lab-a", tmp_path)
    second = StationLock("lab-a", tmp_path)
    with first, pytest.raises(StationLocked, match="used by another process"):
        second.acquire(timeout=0)
    with second:
        pass


def test_other_station_is_independent(tmp_path):
    with StationLock("lab-a", tmp_path), StationLock("lab-b", tmp_path):
        pass


def test_station_name_is_sanitized(tmp_path):
    lock = StationLock("../evil name", tmp_path)
    assert lock.path.parent == tmp_path
    assert lock.path.name == "hil-.._evil_name.lock"


def test_os_error_on_acquire_becomes_station_locked(tmp_path, monkeypatch):
    lock = StationLock("lab-a", tmp_path)

    def deny(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(lock._lock, "acquire", deny)
    with pytest.raises(StationLocked, match=r"cannot use lock file .*hil-lab-a\.lock"):
        lock.acquire()
