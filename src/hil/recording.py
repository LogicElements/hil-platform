"""Per-test artifacts: event log and other JSON Lines files."""

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from hil import clock

log = logging.getLogger("hil.recording")

_LOCK_TIMEOUT_S = 0.5


class Recorder:
    """Writes artifacts of the currently running test into its directory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dir: Path | None = None
        self._t0 = 0.0
        self._start_utc = ""
        self._files: dict[str, IO[str]] = {}

    @property
    def test_dir(self) -> Path | None:
        return self._dir

    def start_test(self, test_dir: Path) -> None:
        with self._lock:
            self._close_files()
            test_dir.mkdir(parents=True, exist_ok=True)
            self._dir = test_dir
            self._t0 = clock.now()
            self._start_utc = datetime.now(UTC).isoformat()

    def stop_test(self) -> None:
        with self._lock:
            self._close_files()
            self._dir = None

    def relative(self, t: float) -> float:
        """Time ``t`` (from ``hil.clock.now``) relative to the start of the test."""
        return t - self._t0

    def write(self, filename: str, record: dict[str, Any]) -> None:
        """Append one JSON record to ``filename`` in the test directory.

        The lock is taken with a timeout: a termination signal handler may call this
        while the interrupted main thread holds the lock, and waiting forever would
        hang the emergency switch-off. A record is dropped instead of deadlocking.
        """
        if not self._lock.acquire(timeout=_LOCK_TIMEOUT_S):
            log.warning("recorder busy, dropping %s record %s", filename, record)
            return
        try:
            if self._dir is None:
                log.debug("no test running, dropping %s record %s", filename, record)
                return
            file = self._files.get(filename)
            if file is None:
                file = (self._dir / filename).open("w", encoding="utf-8")
                file.write(json.dumps({"start_utc": self._start_utc}) + "\n")
                self._files[filename] = file
            file.write(json.dumps(record, default=str) + "\n")
            file.flush()
        finally:
            self._lock.release()

    def event(self, source: str, action: str, **data: Any) -> None:
        t = round(self.relative(clock.now()), 6)
        self.write("events.jsonl", {"t": t, "source": source, "action": action, **data})

    def _close_files(self) -> None:
        for file in self._files.values():
            file.close()
        self._files.clear()
