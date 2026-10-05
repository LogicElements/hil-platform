"""Exclusive lock of a station.

The lock file is shared per machine on Linux (``/run/lock``) and per user on Windows
(the user's temporary directory).
"""

import contextlib
import os
import re
import sys
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from hil.errors import HilError


class StationLocked(HilError):
    """Another process uses the station."""


def lock_dir() -> Path:
    run_lock = Path("/run/lock")
    if sys.platform != "win32" and run_lock.is_dir() and os.access(run_lock, os.W_OK):
        return run_lock
    return Path(tempfile.gettempdir())


class StationLock:
    def __init__(self, station: str, directory: Path | None = None) -> None:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", station).replace("/", "_")
        self.path = (directory or lock_dir()) / f"hil-{safe_name}.lock"
        self._lock = FileLock(str(self.path), mode=0o666)

    def acquire(self, timeout: float = 0.0) -> None:
        try:
            self._lock.acquire(timeout=timeout)
        except Timeout as exc:
            raise StationLocked(
                f"station is used by another process (lock file {self.path})"
            ) from exc
        except OSError as exc:
            raise StationLocked(f"cannot use lock file {self.path}: {exc}") from exc
        # The umask may have stripped the bits requested above; let other users lock too.
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o666)

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "StationLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
