import time

import hil
from hil import clock, errors


def test_version_is_defined():
    assert hil.__version__ == "0.1.0"


def test_error_hierarchy():
    assert issubclass(errors.DeviceNotFound, errors.DeviceError)
    assert issubclass(errors.DeviceTimeout, errors.DeviceError)
    for cls in (
        errors.ConfigError,
        errors.DeviceError,
        errors.SignalUnavailable,
        errors.ResourceConflict,
        errors.OperationNotAllowed,
        errors.WaitTimeout,
    ):
        assert issubclass(cls, errors.HilError)
    assert issubclass(errors.WaitTimeout, TimeoutError)


def test_clock_is_perf_counter():
    assert clock.now is time.perf_counter
    assert clock.now() <= clock.now()
