"""OpenOCD as the debug probe of the DUT (driver ``openocd``)."""

import logging
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from hil import clock
from hil.drivers.base import Device, DriverConfig
from hil.drivers.registry import register_driver
from hil.errors import DeviceError, DeviceNotFound
from hil.resources import ProbeResult

log = logging.getLogger("hil.drivers.openocd")

# bound of the wait for the output of a killed OpenOCD process
_COLLECT_TIMEOUT_S = 5.0


class OpenOcdConfig(DriverConfig):
    # program and leading arguments; OpenOCD from PATH by default
    command: list[str] = Field(default_factory=lambda: ["openocd"], min_length=1)
    # adapter configuration (ST-Link V2 and V3)
    interface: str = "interface/stlink.cfg"
    # serial number of the adapter when more of them are connected
    adapter_serial: str | None = None
    # SWD clock; the target configuration's default when not given
    speed_khz: int | None = Field(default=None, gt=0)
    # extra directories with configuration scripts (-s)
    search: list[str] = Field(default_factory=list)


@register_driver("openocd")
class OpenOcd(Device):
    """Runs one OpenOCD process per operation and returns its output."""

    Config = OpenOcdConfig
    config: OpenOcdConfig

    def __init__(self, name: str, config: OpenOcdConfig) -> None:
        super().__init__(name, config)
        self._program: str | None = None

    @property
    def is_open(self) -> bool:
        return self._program is not None

    def open(self) -> None:
        program = self.config.command[0]
        found = shutil.which(program)
        if found is None:
            raise DeviceNotFound(
                f"device {self.name!r}: OpenOCD program {program!r} not found; "
                "install OpenOCD or set 'command'"
            )
        self._program = found

    def close(self) -> None:
        self._program = None

    def arguments(self, target: str, commands: Sequence[str]) -> list[str]:
        """Command line of one run: adapter, target and ``commands`` (each with -c)."""
        if self._program is None:
            raise DeviceError(f"device {self.name!r} is not open")
        cfg = self.config
        args = [self._program, *cfg.command[1:]]
        for directory in cfg.search:
            args += ["-s", directory]
        args += ["-f", cfg.interface]
        if cfg.adapter_serial is not None:
            args += ["-c", f"adapter serial {cfg.adapter_serial}"]
        args += ["-f", target]
        # after the target: target configurations set their own adapter speed
        if cfg.speed_khz is not None:
            args += ["-c", f"adapter speed {cfg.speed_khz}"]
        for command in commands:
            args += ["-c", command]
        return args

    def flash(
        self, image: Path, target: str, timeout_s: float, abort_after_s: float | None = None
    ) -> ProbeResult:
        # braces keep a path with spaces one Tcl word; OpenOCD wants forward slashes
        program = f"program {{{image.resolve().as_posix()}}} verify reset exit"
        return self._run("flash", self.arguments(target, [program]), timeout_s, abort_after_s)

    def reset(self, target: str, timeout_s: float) -> ProbeResult:
        args = self.arguments(target, ["init", "reset run", "shutdown"])
        return self._run("reset", args, timeout_s, None)

    def halt(self, target: str, timeout_s: float) -> ProbeResult:
        args = self.arguments(target, ["init", "halt", "shutdown"])
        return self._run("halt", args, timeout_s, None)

    def _run(
        self, action: str, args: list[str], timeout_s: float, abort_after_s: float | None
    ) -> ProbeResult:
        limit = timeout_s if abort_after_s is None else min(timeout_s, abort_after_s)
        with self.lock:
            log.debug("%s: running %s", self.name, args)
            start = clock.now()
            try:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise DeviceNotFound(f"device {self.name!r}: cannot start OpenOCD: {exc}") from exc
            try:
                output, _ = process.communicate(timeout=limit)
                stopped = False
            except subprocess.TimeoutExpired:
                process.kill()
                output = self._collect(process)
                stopped = True
            except BaseException:
                # e.g. TerminationRequested: never leave OpenOCD running behind the station
                process.kill()
                self._collect(process)
                raise
            duration = clock.now() - start
        interrupted = stopped and abort_after_s is not None and abort_after_s <= timeout_s
        return ProbeResult(
            action,
            output,
            None if stopped else process.returncode,
            duration,
            interrupted=interrupted,
            timed_out=stopped and not interrupted,
        )

    def _collect(self, process: subprocess.Popen[str]) -> str:
        """Output of the killed ``process``; bounded when a grandchild keeps the pipe open."""
        try:
            output, _ = process.communicate(timeout=_COLLECT_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            # on Windows a daemon reader thread of communicate() still blocks in read() and
            # holds the stream's lock, so closing it there would hang; the thread is left
            if process.stdout is not None and sys.platform != "win32":
                process.stdout.close()
            log.warning(
                "%s: OpenOCD was killed but did not close its output within %s s",
                self.name,
                _COLLECT_TIMEOUT_S,
            )
            gathered = exc.output
            if isinstance(gathered, bytes):
                return gathered.decode("utf-8", errors="replace")
            return gathered or ""
        return output
