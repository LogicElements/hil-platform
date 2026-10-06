"""Pydantic models of the profile, station and DUT configuration files."""

import keyword
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hil.config.refs import Ref, ResourceRef

__all__ = [
    "PARAM_MODELS",
    "AnalogConfig",
    "DebugParams",
    "DutConfig",
    "Profile",
    "SerialParams",
    "StationConfig",
    "StationTerminal",
    "signal_params",
    "terminal_refs",
]

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


class AnalogConfig(_Strict):
    """Generators switched by the output multiplexers.

    ``generators[0]`` is selected by a released ``select`` relay (NC contact),
    ``generators[1]`` by an operated one (NO contact).
    """

    generators: list[Ref] = Field(min_length=2, max_length=2)


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
    analog: AnalogConfig | None = None
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
        # scope channel -> (terminal, has a connect relay); a scope may be shared
        scopes: dict[ResourceRef, list[tuple[str, bool]]] = {}
        for name, terminal in self.terminals.items():
            refs = terminal_refs(terminal)
            devices = [ref.device for ref in refs]
            if isinstance(terminal, DebugTerminal):
                devices.append(terminal.probe)
            for device in devices:
                if device not in self.devices:
                    raise ValueError(f"terminal {name!r} refers to unknown device {device!r}")
            uses_mux = isinstance(terminal, AnalogOutTerminal) and terminal.select is not None
            if uses_mux and self.analog is None:
                raise ValueError(
                    f"terminal {name!r} uses the output multiplexer; list its generators "
                    "in 'analog: {generators: [<generator 1>, <generator 2>]}'"
                )
            if isinstance(terminal, AnalogInTerminal):
                scopes.setdefault(terminal.scope, []).append((name, terminal.connect is not None))
                refs = [ref for ref in refs if ref != terminal.scope]
            for ref in refs:
                if ref in used:
                    raise ValueError(f"resource {ref} is used by both {used[ref]!r} and {name!r}")
                used[ref] = name
        for scope, users in scopes.items():
            if scope in used:
                raise ValueError(
                    f"resource {scope} is used by both {used[scope]!r} and {users[0][0]!r}"
                )
            if len(users) > 1 and not all(has_connect for _, has_connect in users):
                names = ", ".join(repr(name) for name, _ in users)
                raise ValueError(
                    f"scope channel {scope} is shared by {names}; every terminal sharing "
                    "a scope channel needs a 'connect' relay"
                )
        if self.analog is not None:
            self._check_generators(self.analog.generators, used)
        return self

    def _check_generators(
        self, generators: list[ResourceRef], used: dict[ResourceRef, str]
    ) -> None:
        for ref in generators:
            if ref.device not in self.devices:
                raise ValueError(f"analog generator {ref} refers to unknown device {ref.device!r}")
        if generators[0] == generators[1]:
            raise ValueError(f"analog generators must differ, got {generators[0]} twice")
        for ref in generators:
            owner = used.get(ref)
            if owner is None:
                continue
            terminal = self.terminals[owner]
            if not (isinstance(terminal, AnalogOutTerminal) and terminal.direct == ref):
                raise ValueError(f"analog generator {ref} is also used by terminal {owner!r}")


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


class SerialParams(_Strict):
    """Line parameters of a ``serial``, ``rs485`` or ``rs485_monitor`` DUT signal."""

    baud: int = Field(default=115200, gt=0)
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    bytesize: Literal[7, 8] = 8
    # rs485: how long the Modbus master waits for a response
    timeout_s: float = Field(default=1.0, gt=0)
    # rs485: the transceiver echoes what the platform sends
    echo: bool = False
    # rs485_monitor: silence that ends a frame; default 3.5 characters, at least 1.5 ms
    frame_gap_s: float | None = Field(default=None, gt=0)

    def char_time_s(self) -> float:
        """Duration of one character on the line (start, data, parity and stop bits)."""
        bits = 1 + self.bytesize + (0 if self.parity == "N" else 1) + self.stopbits
        return bits / self.baud

    def gap_s(self) -> float:
        if self.frame_gap_s is not None:
            return self.frame_gap_s
        return max(3.5 * self.char_time_s(), 0.0015)


DEFAULT_DEBUG_TIMEOUT_S = 120.0


class DebugParams(_Strict):
    """Parameters of a ``debug`` DUT signal."""

    # OpenOCD target configuration, e.g. target/stm32g4x.cfg
    target: str = Field(min_length=1)
    # longest duration of one probe operation (flashing a large image takes tens of seconds)
    timeout_s: float = Field(default=DEFAULT_DEBUG_TIMEOUT_S, gt=0)


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "serial": SerialParams,
    "rs485": SerialParams,
    "rs485_monitor": SerialParams,
    "debug": DebugParams,
}


def signal_params(kind: str, params: dict[str, Any]) -> BaseModel | None:
    """Validated parameters of a DUT signal on a terminal of ``kind``.

    Raises ``ValueError`` (pydantic's ``ValidationError`` included) for invalid ones.
    """
    model = PARAM_MODELS.get(kind)
    if model is None:
        if params:
            raise ValueError(f"terminal kind {kind!r} takes no parameters, got {sorted(params)}")
        return None
    return model.model_validate(params)
