"""Debug terminal: flashing and control of the DUT's microcontroller (kind ``debug``)."""

from pathlib import Path

from hil.config.models import DEFAULT_DEBUG_TIMEOUT_S, DebugParams
from hil.errors import DeviceError, DeviceTimeout, OperationNotAllowed
from hil.recording import Recorder
from hil.resources import DebugProbe, ProbeResult
from hil.signals.base import Signal

LOG_FILE = "openocd.log"


class DebugSignal(Signal):
    """Debug probe of a terminal; the target comes from the DUT signal or from the call."""

    kind = "debug"

    def __init__(self, name: str, recorder: Recorder, probe: DebugProbe) -> None:
        super().__init__(name, recorder)
        self.probe = probe
        self.alias = name
        self.params: DebugParams | None = None

    def configure(self, alias: str, params: DebugParams) -> None:
        """Use the DUT signal name ``alias`` in the log and the DUT's target."""
        self.alias = alias
        self.params = params

    def flash(self, image: str | Path, target: str | None = None) -> ProbeResult:
        """Program ``image`` into the DUT, verify it and let the DUT run."""
        path = _image(image)
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.flash(path, target, timeout_s), image=str(path))

    def flash_interrupted(
        self, image: str | Path, after_s: float, target: str | None = None
    ) -> ProbeResult:
        """Start flashing ``image`` and stop the probe after ``after_s`` seconds.

        ``interrupted`` of the result is False when flashing finished earlier.
        """
        if after_s <= 0:
            raise ValueError("after_s must be positive")
        path = _image(image)
        target, timeout_s = self._settings(target)
        result = self.probe.flash(path, target, timeout_s, abort_after_s=after_s)
        return self._finish(result, image=str(path), after_s=after_s)

    def reset(self, target: str | None = None) -> ProbeResult:
        """Reset the DUT and let it run."""
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.reset(target, timeout_s))

    def halt(self, target: str | None = None) -> ProbeResult:
        """Stop the DUT's core."""
        target, timeout_s = self._settings(target)
        return self._finish(self.probe.halt(target, timeout_s))

    def _settings(self, target: str | None) -> tuple[str, float]:
        timeout_s = DEFAULT_DEBUG_TIMEOUT_S if self.params is None else self.params.timeout_s
        if target is not None:
            return target, timeout_s
        if self.params is None:
            raise OperationNotAllowed(
                f"{self.alias}: no debug target; set 'target' of the DUT signal or pass target="
            )
        return self.params.target, timeout_s

    def _finish(self, result: ProbeResult, **data: object) -> ProbeResult:
        self.recorder.write_line(LOG_FILE, f"--- {self.alias}: {result.action}")
        for line in result.output.splitlines():
            self.recorder.write_line(LOG_FILE, line)
        self._event(
            result.action,
            returncode=result.returncode,
            duration_s=round(result.duration_s, 3),
            interrupted=result.interrupted,
            **data,
        )
        if result.timed_out:
            raise DeviceTimeout(
                f"{self.alias}: {result.action} did not finish in time; output in {LOG_FILE}"
            )
        if not result.interrupted and result.returncode != 0:
            last = result.output.strip().splitlines()[-1:] or ["no output"]
            raise DeviceError(
                f"{self.alias}: {result.action} failed with exit code {result.returncode}: "
                f"{last[0]} (output in {LOG_FILE})"
            )
        return result

    def safe_state(self) -> None:
        """Nothing to do: every probe operation ends before its call returns."""


def _image(image: str | Path) -> Path:
    path = Path(image)
    if not path.is_file():
        raise FileNotFoundError(f"firmware image {path} not found")
    return path
