"""Single clock used for all timestamps of the platform."""

import time

# time.monotonic() has ~16 ms resolution on Windows before Python 3.13;
# perf_counter() is monotonic with sub-microsecond resolution everywhere.
now = time.perf_counter
