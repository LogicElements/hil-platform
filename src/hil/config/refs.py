"""Resource references in the form ``<device>.<channel>``."""

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import PlainSerializer, PlainValidator


@dataclass(frozen=True)
class ResourceRef:
    """Reference to one channel of one device, e.g. ``rel1.6``."""

    device: str
    channel: str

    @classmethod
    def parse(cls, text: str) -> "ResourceRef":
        device, sep, channel = text.partition(".")
        if not sep or not device or not channel or "." in channel:
            raise ValueError(f"invalid resource reference {text!r}, expected '<device>.<channel>'")
        return cls(device, channel)

    def __str__(self) -> str:
        return f"{self.device}.{self.channel}"


def _coerce(value: Any) -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if not isinstance(value, str):
        raise ValueError(f"resource reference must be a string like 'rel1.6', got {value!r}")
    return ResourceRef.parse(value)


Ref = Annotated[ResourceRef, PlainValidator(_coerce), PlainSerializer(str)]
