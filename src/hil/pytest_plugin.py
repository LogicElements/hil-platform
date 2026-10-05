"""pytest plugin: station and DUT fixtures, skipping of unwired signals, safe state."""

import hashlib
import os
import re
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest

from hil.config.loader import load_dut
from hil.config.models import DutConfig
from hil.dut import Dut
from hil.errors import ConfigError, HilError, SignalUnavailable
from hil.locking import StationLock
from hil.station import Station

EXIT_STATION_FAILURE = 3


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("hil", "HIL platform")
    group.addoption(
        "--hil-station",
        default=None,
        help="station file or built-in station name (default: $HIL_STATION)",
    )
    group.addoption("--hil-dut", default=None, help="DUT wiring file (default: $HIL_DUT)")
    group.addoption("--hil-out", default="out", help="directory for per-test artifacts")
    group.addoption(
        "--hil-profiles",
        action="append",
        default=[],
        help="additional directory with connector profiles (may be repeated)",
    )
    group.addoption(
        "--hil-lock-timeout",
        type=float,
        default=0.0,
        help="seconds to wait for the station lock (default: 0)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "hil_requires(*signals): skip unless all named DUT signals are wired on the station",
    )


def _option(config: pytest.Config, name: str, env: str) -> str | None:
    value = config.getoption(name) or os.environ.get(env)
    return value or None


def artifact_dir_name(nodeid: str) -> str:
    """Directory name for the artifacts of a test, safe on Linux and Windows."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", nodeid).strip("_")
    truncated = name[:150]
    if truncated != nodeid:
        # Sanitizing or truncation may map different tests to one name; keep them apart.
        digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:8]
        truncated = f"{truncated}-{digest}"
    return truncated.rstrip(".") or "test"


@pytest.fixture(scope="session")
def hil(request: pytest.FixtureRequest) -> Iterator[Station]:
    config = request.config
    spec = _option(config, "--hil-station", "HIL_STATION")
    if spec is None:
        pytest.fail("no HIL station configured: pass --hil-station or set HIL_STATION", False)
    profile_dirs = [Path(p) for p in config.getoption("--hil-profiles")]
    try:
        station = Station.from_files(spec, profile_dirs)
    except ConfigError as exc:
        pytest.exit(f"HIL configuration error: {exc}", returncode=pytest.ExitCode.USAGE_ERROR)
    lock = StationLock(station.name)
    try:
        lock.acquire(config.getoption("--hil-lock-timeout"))
    except HilError as exc:
        pytest.exit(f"HIL station {station.name!r}: {exc}", returncode=EXIT_STATION_FAILURE)
    try:
        station.open()
    except Exception as exc:
        lock.release()
        pytest.exit(
            f"HIL station {station.name!r} cannot be opened: {exc}",
            returncode=EXIT_STATION_FAILURE,
        )
    try:
        station.install_emergency_handlers()
        yield station
    finally:
        try:
            station.close()
        except HilError as exc:
            # Raising here would turn into an internal error of the pytest session.
            config.get_terminal_writer().line(
                f"HIL station {station.name!r}: closing failed: {exc}", red=True
            )
        finally:
            lock.release()


@pytest.fixture(scope="session")
def hil_dut_config(hil: Station, request: pytest.FixtureRequest) -> DutConfig:
    path = _option(request.config, "--hil-dut", "HIL_DUT")
    if path is None:
        pytest.fail("no DUT wiring configured: pass --hil-dut or set HIL_DUT", False)
    try:
        return load_dut(path, hil.profile)
    except ConfigError as exc:
        pytest.exit(f"HIL configuration error: {exc}", returncode=pytest.ExitCode.USAGE_ERROR)


@pytest.fixture
def dut(hil: Station, hil_dut_config: DutConfig, request: pytest.FixtureRequest) -> Dut:
    device = Dut(hil_dut_config, hil)
    marker = request.node.get_closest_marker("hil_requires")
    if marker is not None:
        for name in marker.args:
            if name not in hil_dut_config.signals:
                pytest.fail(f"hil_requires: DUT {device.name!r} has no signal {name!r}", False)
            if not device.available(name):
                terminal = hil_dut_config.signals[name].terminal
                pytest.skip(
                    f"signal {name!r}: terminal {terminal!r} is not wired on station {hil.name!r}"
                )
    return device


@pytest.fixture(autouse=True)
def _hil_test_boundary(request: pytest.FixtureRequest) -> Iterator[None]:
    """Artifacts and safe state around every test that uses ``hil`` (or ``dut``)."""
    if "hil" not in request.fixturenames:
        yield
        return
    station: Station = request.getfixturevalue("hil")
    out = Path(request.config.getoption("--hil-out"))
    station.recorder.start_test(out / artifact_dir_name(request.node.nodeid))
    try:
        yield
    finally:
        try:
            station.safe_state()
        except HilError as exc:
            pytest.exit(
                f"HIL station {station.name!r} could not reach the safe state, stopping: {exc}",
                returncode=EXIT_STATION_FAILURE,
            )
        finally:
            station.recorder.stop_test()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Report an unwired signal as a skip, whatever the scope of the fixture that raised it."""
    report = yield
    if (
        call.excinfo is not None
        and call.excinfo.errisinstance(SignalUnavailable)
        and call.when in ("setup", "call")
    ):
        path, lineno, _ = item.reportinfo()
        report.outcome = "skipped"
        report.longrepr = (str(path), (lineno or 0) + 1, f"Skipped: {call.excinfo.value}")
    return report
