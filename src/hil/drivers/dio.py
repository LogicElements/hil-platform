"""Digital I/O lines of the Analog Discovery 3, shared by the real and simulated driver."""

from typing import Annotated, Protocol

from pydantic import Field, model_validator

from hil.drivers.base import DriverConfig
from hil.resources import DigitalInput, InputBank, LogicOutput, OutputBank

DIO_LINES = 16
DIO_CHANNELS = {f"dio{line}": line for line in range(DIO_LINES)}

Line = Annotated[int, Field(ge=0, lt=DIO_LINES)]


class DioConfig(DriverConfig):
    # lines driven by the station (logic_out terminals); all other lines are inputs
    dio_outputs: list[Line] = Field(default_factory=list)
    # input lines read inverted: level 0 reads True (dry contact with a pull-up)
    dio_invert: list[Line] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_lines(self) -> "DioConfig":
        for option in ("dio_outputs", "dio_invert"):
            lines = getattr(self, option)
            if len(set(lines)) != len(lines):
                raise ValueError(f"{option} lists a line more than once")
        both = sorted(set(self.dio_outputs) & set(self.dio_invert))
        if both:
            raise ValueError(f"output lines {both} cannot be in dio_invert")
        return self


class DioBank(InputBank, OutputBank, Protocol):
    """A device whose digital lines are inputs or logic outputs."""


def dio_resource(bank: DioBank, config: DioConfig, line: int) -> DigitalInput | LogicOutput:
    """Resource of ``line``: a logic output if configured as one, an input otherwise."""
    if line in config.dio_outputs:
        return LogicOutput(bank, line)
    return DigitalInput(bank, line)
