"""Simulated debug probe (driver ``sim_probe``)."""

import time
from pathlib import Path

from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError
from hil.resources import ProbeResult


class SimProbeConfig(DriverConfig):
    # how long a simulated flashing takes
    flash_s: float = Field(default=0.05, ge=0)


@register_driver("sim_probe")
class SimProbe(Device):
    """Records flash, reset and halt; ``returncode`` and ``fail_with`` simulate failures."""

    Config = SimProbeConfig
    config: SimProbeConfig

    def __init__(self, name: str, config: SimProbeConfig) -> None:
        super().__init__(name, config)
        # (time, action, target, image)
        self.calls: list[tuple[float, str, str, str | None]] = []
        self.returncode = 0
        self.fail_with: Exception | None = None
        self.is_open = False

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def _run(
        self,
        action: str,
        target: str,
        image: str | None,
        duration_s: float,
        timeout_s: float,
        abort_after_s: float | None,
    ) -> ProbeResult:
        with self.lock:
            if self.fail_with is not None:
                raise self.fail_with
            if not self.is_open:
                raise DeviceError(f"device {self.name!r} is not open")
            start = clock.now()
            limit = timeout_s if abort_after_s is None else min(timeout_s, abort_after_s)
            stopped = duration_s > limit
            time.sleep(min(duration_s, limit))
            self.calls.append((start, action, target, image))
            interrupted = stopped and abort_after_s is not None and abort_after_s <= timeout_s
            output = f"sim_probe {action} target={target}"
            if image is not None:
                output += f" image={image}"
            return ProbeResult(
                action,
                output + "\n",
                None if stopped else self.returncode,
                clock.now() - start,
                interrupted=interrupted,
                timed_out=stopped and not interrupted,
            )

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult:
        return self._run("flash", target, str(image), self.config.flash_s, timeout_s, abort_after_s)

    def reset(self, target: str, timeout_s: float) -> ProbeResult:
        return self._run("reset", target, None, 0.0, timeout_s, None)

    def halt(self, target: str, timeout_s: float) -> ProbeResult:
        return self._run("halt", target, None, 0.0, timeout_s, None)
