"""Pydantic models of the profile, station and DUT configuration files."""

import keyword
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hil.config.refs import Ref, ResourceRef

TerminalKind = Literal[
    "power",
    "switch",
    "sense",
    "fault_path",
    "analog_out",
    "analog_in",
    "serial",
    "rs485",
    "rs485_monitor",
    "debug",
]

DEVICE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

# Attribute names of hil.dut.Dut that a signal name must not shadow.
RESERVED_SIGNAL_NAMES = frozenset({"name", "config", "station", "signal", "params", "available"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Profile(_Strict):
    """Connector profile: every terminal a station of this type may have."""

    profile: str
    terminals: dict[str, TerminalKind] = Field(min_length=1)


class PowerTerminal(_Strict):
    kind: Literal["power"]
    relays: list[Ref] = Field(min_length=1)


class SwitchTerminal(_Strict):
    kind: Literal["switch"]
    relay: Ref


class SenseTerminal(_Strict):
    kind: Literal["sense"]
    input: Ref


class FaultPathTerminal(_Strict):
    kind: Literal["fault_path"]
    series: Ref
    short: Ref | None = None
    carries_power: bool = False
    allow_short: bool = False


class AnalogOutTerminal(_Strict):
    kind: Literal["analog_out"]
    direct: Ref | None = None
    select: Ref | None = None
    connect: Ref | None = None

    @model_validator(mode="after")
    def _direct_or_mux(self) -> "AnalogOutTerminal":
        has_direct = self.direct is not None
        has_mux = self.select is not None and self.connect is not None
        has_partial_mux = (self.select is None) != (self.connect is None)
        if has_partial_mux or has_direct == has_mux:
            raise ValueError("analog_out needs either 'direct', or both 'select' and 'connect'")
        return self


class AnalogInTerminal(_Strict):
    kind: Literal["analog_in"]
    scope: Ref
    connect: Ref | None = None
    settle_s: float = Field(default=0.02, ge=0)


class SerialTerminal(_Strict):
    kind: Literal["serial"]
    port: Ref


class Rs485Terminal(_Strict):
    kind: Literal["rs485"]
    port: Ref


class Rs485MonitorTerminal(_Strict):
    kind: Literal["rs485_monitor"]
    port: Ref


class DebugTerminal(_Strict):
    kind: Literal["debug"]
    probe: str


StationTerminal = Annotated[
    PowerTerminal
    | SwitchTerminal
    | SenseTerminal
    | FaultPathTerminal
    | AnalogOutTerminal
    | AnalogInTerminal
    | SerialTerminal
    | Rs485Terminal
    | Rs485MonitorTerminal
    | DebugTerminal,
    Field(discriminator="kind"),
]


def terminal_refs(terminal: BaseModel) -> list[ResourceRef]:
    """All resource references of a terminal, in field order."""
    refs: list[ResourceRef] = []
    for field in type(terminal).model_fields:
        value = getattr(terminal, field)
        if isinstance(value, ResourceRef):
            refs.append(value)
        elif isinstance(value, list):
            refs.extend(item for item in value if isinstance(item, ResourceRef))
    return refs


class DeviceConfig(BaseModel):
    """A device entry; options other than ``driver`` are validated by the driver."""

    model_config = ConfigDict(extra="allow", frozen=True)

    driver: str

    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class StationConfig(_Strict):
    name: str
    labels: list[str] = Field(default_factory=list)
    profile: str
    devices: dict[str, DeviceConfig]
    terminals: dict[str, StationTerminal]

    @field_validator("devices")
    @classmethod
    def _device_names(cls, devices: dict[str, DeviceConfig]) -> dict[str, DeviceConfig]:
        for name in devices:
            if not DEVICE_NAME.match(name):
                raise ValueError(
                    f"device name {name!r} must start with a letter or '_' and contain "
                    "only letters, digits, '_' and '-'"
                )
        return devices

    @model_validator(mode="after")
    def _check_references(self) -> "StationConfig":
        used: dict[ResourceRef, str] = {}
        for name, terminal in self.terminals.items():
            refs = terminal_refs(terminal)
            devices = [ref.device for ref in refs]
            if isinstance(terminal, DebugTerminal):
                devices.append(terminal.probe)
            for device in devices:
                if device not in self.devices:
                    raise ValueError(f"terminal {name!r} refers to unknown device {device!r}")
            for ref in refs:
                if ref in used:
                    raise ValueError(f"resource {ref} is used by both {used[ref]!r} and {name!r}")
                used[ref] = name
        return self


class SignalSpec(BaseModel):
    """A DUT signal; fields other than ``terminal`` are parameters of the signal."""

    model_config = ConfigDict(extra="allow", frozen=True)

    terminal: str

    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class DutConfig(_Strict):
    dut: str
    profile: str
    signals: dict[str, SignalSpec]

    @field_validator("signals", mode="before")
    @classmethod
    def _expand_shorthand(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: {"terminal": v} if isinstance(v, str) else v for k, v in value.items()}
        return value

    @field_validator("signals")
    @classmethod
    def _signal_names(cls, signals: dict[str, SignalSpec]) -> dict[str, SignalSpec]:
        for name in signals:
            if (
                not name.isidentifier()
                or keyword.iskeyword(name)
                or name.startswith("_")
                or name in RESERVED_SIGNAL_NAMES
            ):
                raise ValueError(
                    f"signal name {name!r} must be a Python identifier, must not start "
                    f"with '_' and must not be one of {sorted(RESERVED_SIGNAL_NAMES)}"
                )
        return signals
