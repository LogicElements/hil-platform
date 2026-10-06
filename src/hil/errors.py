"""Exceptions raised by the HIL platform."""


class HilError(Exception):
    """Base of all HIL platform errors."""


class ConfigError(HilError):
    """Invalid profile, station or DUT configuration."""


class DeviceError(HilError):
    """A device failed or reported an error."""


class DeviceNotFound(DeviceError):
    """A configured device is not connected or cannot be opened."""


class DeviceTimeout(DeviceError):
    """A device did not answer in time."""


class SignalUnavailable(HilError):
    """The signal or terminal is not wired on this station; tests using it are skipped."""


class ResourceConflict(HilError):
    """Two operations need the same resource at the same time."""


class OperationNotAllowed(HilError):
    """The operation is refused in the current state or by the station configuration."""


class WaitTimeout(HilError, TimeoutError):
    """An awaited state of the DUT was not reached in time."""


class TerminationRequested(KeyboardInterrupt):
    """A termination signal arrived; raised in the main thread so that cleanup runs.

    A subclass of ``KeyboardInterrupt``: pytest ends the session and tears the fixtures
    down as after Ctrl+C, while a ``SystemExit`` raised in a test would only fail that
    test and the session would go on.
    """

    def __init__(self, signame: str) -> None:
        super().__init__(signame)
        self.signame = signame
