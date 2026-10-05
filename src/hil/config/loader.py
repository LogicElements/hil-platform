"""Loading of profile, station and DUT files and checks between them."""

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from hil.config.models import DutConfig, Profile, StationConfig
from hil.errors import ConfigError


def _builtin_dir(kind: str) -> Path:
    return Path(str(resources.files("hil") / kind))


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"{path}: file is not valid UTF-8: {exc.reason} at byte {exc.start}"
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _format_errors(path: Path, exc: ValidationError) -> str:
    lines = [f"{path}: invalid configuration"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)


def parse_file[M: BaseModel](path: Path, model: type[M]) -> M:
    data = read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_errors(path, exc)) from exc


def load_profile(name: str, extra_dirs: Sequence[Path] = ()) -> Profile:
    directories = [*extra_dirs, _builtin_dir("profiles")]
    for directory in directories:
        path = directory / f"{name}.yaml"
        if path.is_file():
            profile = parse_file(path, Profile)
            if profile.profile != name:
                raise ConfigError(
                    f"{path}: file declares profile {profile.profile!r}, expected {name!r}"
                )
            return profile
    searched = ", ".join(str(d) for d in directories)
    raise ConfigError(f"profile {name!r} not found (searched: {searched})")


def resolve_station_path(spec: str | Path) -> Path:
    """Return the station file for a path or the name of a built-in station."""
    path = Path(spec)
    if path.suffix in (".yaml", ".yml") or len(path.parts) > 1:
        return path
    builtin = _builtin_dir("stations") / f"{spec}.yaml"
    if builtin.is_file():
        return builtin
    if path.is_file():
        return path
    names = sorted(p.stem for p in _builtin_dir("stations").glob("*.yaml"))
    raise ConfigError(
        f"station {str(spec)!r} is neither a file nor a built-in station "
        f"(built-in: {', '.join(names) or 'none'})"
    )


def _check_station(station: StationConfig, profile: Profile, source: Path) -> None:
    for name, terminal in station.terminals.items():
        expected = profile.terminals.get(name)
        if expected is None:
            raise ConfigError(
                f"{source}: terminal {name!r} is not defined in profile {profile.profile!r}"
            )
        if terminal.kind != expected:
            raise ConfigError(
                f"{source}: terminal {name!r} has kind {terminal.kind!r}, "
                f"profile {profile.profile!r} defines {expected!r}"
            )


@dataclass(frozen=True)
class LoadedStation:
    config: StationConfig
    profile: Profile
    source: Path


def load_station(spec: str | Path, profile_dirs: Sequence[Path] = ()) -> LoadedStation:
    path = resolve_station_path(spec)
    config = parse_file(path, StationConfig)
    profile = load_profile(config.profile, profile_dirs)
    _check_station(config, profile, path)
    return LoadedStation(config, profile, path)


def load_dut(path: str | Path, profile: Profile) -> DutConfig:
    path = Path(path)
    dut = parse_file(path, DutConfig)
    if dut.profile != profile.profile:
        raise ConfigError(
            f"{path}: DUT uses profile {dut.profile!r}, station uses {profile.profile!r}"
        )
    for name, spec in dut.signals.items():
        if spec.terminal not in profile.terminals:
            raise ConfigError(
                f"{path}: signal {name!r} refers to terminal {spec.terminal!r}, "
                f"which is not in profile {profile.profile!r}"
            )
    return dut
