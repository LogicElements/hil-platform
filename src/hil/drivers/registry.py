"""Registry of driver classes by the name used in station files."""

from collections.abc import Callable, Mapping
from graphlib import CycleError, TopologicalSorter

from pydantic import ValidationError

from hil.config.models import DeviceConfig
from hil.drivers.base import Device
from hil.errors import ConfigError

_DRIVERS: dict[str, type[Device]] = {}


def register_driver[D: Device](name: str) -> Callable[[type[D]], type[D]]:
    def decorator(cls: type[D]) -> type[D]:
        registered = _DRIVERS.get(name)
        if registered is not None and registered is not cls:
            raise RuntimeError(f"driver {name!r} is already registered")
        _DRIVERS[name] = cls
        return cls

    return decorator


def driver_names() -> list[str]:
    return sorted(_DRIVERS)


def create_device(name: str, config: DeviceConfig) -> Device:
    cls = _DRIVERS.get(config.driver)
    if cls is None:
        known = ", ".join(driver_names())
        raise ConfigError(f"device {name!r}: unknown driver {config.driver!r} (known: {known})")
    try:
        options = cls.Config.model_validate(config.options())
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"device {name!r} ({config.driver}): {details}") from exc
    return cls(name, options)


def open_order(devices: Mapping[str, Device]) -> list[str]:
    """Device names ordered so that every device comes after its dependencies."""
    graph: dict[str, list[str]] = {}
    for name, device in devices.items():
        dependencies = device.dependencies()
        for dependency in dependencies:
            if dependency not in devices:
                raise ConfigError(f"device {name!r} depends on unknown device {dependency!r}")
        graph[name] = dependencies
    try:
        return list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        cycle = " -> ".join(exc.args[1])
        raise ConfigError(f"devices depend on each other in a cycle: {cycle}") from exc
