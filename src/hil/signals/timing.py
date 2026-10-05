"""Timing helpers."""

import time

from hil import clock

_SPIN_S = 0.002


def precise_sleep(seconds: float) -> None:
    """Sleep with sub-millisecond accuracy: coarse sleep, then spin on the clock."""
    deadline = clock.now() + seconds
    coarse = seconds - _SPIN_S
    if coarse > 0:
        time.sleep(coarse)
    while clock.now() < deadline:
        pass
