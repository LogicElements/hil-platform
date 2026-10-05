"""Command line tool ``hil``."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hil.config.loader import load_dut
from hil.errors import ConfigError, HilError
from hil.locking import StationLock
from hil.station import Station

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_DEVICE = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hil", description="HIL platform tools")
    commands = parser.add_subparsers(dest="command", required=True)

    def station_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--station", required=True, help="station file or built-in name")
        command.add_argument(
            "--profiles", action="append", default=[], type=Path, help="extra profile directory"
        )

    check = commands.add_parser("check", help="validate the configuration")
    station_arguments(check)
    check.add_argument("--dut", type=Path, help="DUT wiring file to check against the station")
    check.add_argument("--probe", action="store_true", help="also open all devices")
    station_arguments(commands.add_parser("safe", help="put the station into the safe state"))
    station_arguments(commands.add_parser("info", help="list devices, terminals and blocks"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        station = Station.from_files(args.station, args.profiles)
        if args.command == "check":
            return _check(station, args.dut, args.probe)
        if args.command == "safe":
            return _safe(station)
        return _info(station)
    except ConfigError as exc:
        print(f"configuration error:\n{exc}", file=sys.stderr)
        return EXIT_CONFIG
    except HilError as exc:
        print(f"device error: {exc}", file=sys.stderr)
        return EXIT_DEVICE


def _check(station: Station, dut_path: Path | None, probe: bool) -> int:
    if dut_path is not None:
        dut = load_dut(dut_path, station.profile)
        print(f"DUT {dut.dut!r}: {len(dut.signals)} signals OK")
    if probe:
        with StationLock(station.name), station:
            pass
        print(f"station {station.name!r}: all {len(station.devices)} devices opened")
    print(f"station {station.name!r}: configuration OK")
    return EXIT_OK


def _safe(station: Station) -> int:
    # open() and close() both apply the safe state
    with StationLock(station.name), station:
        pass
    print(f"station {station.name!r}: safe state set")
    return EXIT_OK


def _info(station: Station) -> int:
    print(f"station {station.name} (profile {station.profile.profile}, file {station.source})")
    print("devices:")
    for name, device in station.config.devices.items():
        print(f"  {name:12} {device.driver}")
    print("terminals:")
    for name, kind in station.profile.terminals.items():
        state = "wired" if name in station.terminals else "not wired"
        print(f"  {name:12} {kind:14} {state}")
    blocks = {
        "power": list(station.power.signals),
        "digital": [*station.digital.switches, *station.digital.senses],
        "faults": list(station.faults.paths),
    }
    print("blocks:")
    for block, names in blocks.items():
        print(f"  {block:8} {', '.join(names) or '-'}")
    return EXIT_OK


def run() -> None:
    sys.exit(main())
