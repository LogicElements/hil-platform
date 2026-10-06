"""Modbus RTU frames: CRC, building of requests and decoding."""

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

READ_COILS = 1
READ_DISCRETE_INPUTS = 2
READ_HOLDING_REGISTERS = 3
READ_INPUT_REGISTERS = 4
WRITE_SINGLE_COIL = 5
WRITE_SINGLE_REGISTER = 6
WRITE_MULTIPLE_COILS = 15
WRITE_MULTIPLE_REGISTERS = 16

BIT_READS = frozenset({READ_COILS, READ_DISCRETE_INPUTS})
REGISTER_READS = frozenset({READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS})

MAX_READ_BITS = 2000
MAX_READ_REGISTERS = 125
MAX_WRITE_BITS = 1968
MAX_WRITE_REGISTERS = 123

FrameKind = Literal["request", "response", "exception", "unknown"]


def _crc_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


CRC_TABLE = _crc_table()


def crc16_step(crc: int, byte: int) -> int:
    """Feed one byte into a running CRC-16/MODBUS."""
    return (crc >> 8) ^ CRC_TABLE[(crc ^ byte) & 0xFF]


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS of ``data``."""
    crc = 0xFFFF
    for byte in data:
        crc = crc16_step(crc, byte)
    return crc


def with_crc(body: bytes) -> bytes:
    """``body`` followed by its CRC, low byte first."""
    return body + crc16(body).to_bytes(2, "little")


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def _check(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be in {low}..{high}, got {value}")


def request(address: int, function: int, payload: bytes = b"") -> bytes:
    """A request for ``address`` (0 = broadcast) with ``payload`` and CRC."""
    _check("address", address, 0, 247)
    _check("function", function, 1, 127)
    return with_crc(bytes((address, function)) + payload)


def read_request(address: int, function: int, start: int, count: int) -> bytes:
    if function not in BIT_READS | REGISTER_READS:
        raise ValueError(f"function {function} is not a read function")
    limit = MAX_READ_BITS if function in BIT_READS else MAX_READ_REGISTERS
    _check("start", start, 0, 0xFFFF)
    _check("count", count, 1, limit)
    return request(address, function, struct.pack(">HH", start, count))


def write_coil_request(address: int, coil: int, on: bool) -> bytes:
    _check("coil", coil, 0, 0xFFFF)
    return request(address, WRITE_SINGLE_COIL, struct.pack(">HH", coil, 0xFF00 if on else 0))


def write_register_request(address: int, register: int, value: int) -> bytes:
    _check("register", register, 0, 0xFFFF)
    _check("value", value, 0, 0xFFFF)
    return request(address, WRITE_SINGLE_REGISTER, struct.pack(">HH", register, value))


def write_coils_request(address: int, start: int, values: Sequence[bool]) -> bytes:
    _check("start", start, 0, 0xFFFF)
    _check("count", len(values), 1, MAX_WRITE_BITS)
    packed = pack_bits(values)
    header = struct.pack(">HHB", start, len(values), len(packed))
    return request(address, WRITE_MULTIPLE_COILS, header + packed)


def write_registers_request(address: int, start: int, values: Sequence[int]) -> bytes:
    _check("start", start, 0, 0xFFFF)
    _check("count", len(values), 1, MAX_WRITE_REGISTERS)
    for value in values:
        _check("value", value, 0, 0xFFFF)
    data = struct.pack(f">{len(values)}H", *values)
    header = struct.pack(">HHB", start, len(values), len(data))
    return request(address, WRITE_MULTIPLE_REGISTERS, header + data)


def pack_bits(values: Sequence[bool]) -> bytes:
    """Bits packed LSB first, as Modbus transfers coils and discrete inputs."""
    packed = bytearray((len(values) + 7) // 8)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


def unpack_bits(data: bytes, count: int | None = None) -> list[bool]:
    bits = [bool(data[i // 8] >> (i % 8) & 1) for i in range(len(data) * 8)]
    return bits if count is None else bits[:count]


@dataclass(frozen=True)
class ModbusFrame:
    """A decoded Modbus RTU frame."""

    address: int
    function: int
    kind: FrameKind
    fields: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "address": self.address,
            "function": self.function,
            "kind": self.kind,
            **self.fields,
        }


def decode(frame: bytes) -> ModbusFrame:
    """Decode a frame with a valid CRC.

    Requests and responses are told apart by their length. A single write (functions 5
    and 6) is answered by an identical echo, so both are reported as ``request``. A
    bit-read response with three data bytes has the length of a request and is
    reported as a request.
    """
    if not crc_ok(frame):
        raise ValueError(f"bad CRC in frame {frame.hex(' ')}")
    address, function = frame[0], frame[1]
    data = frame[2:-2]
    if function & 0x80:
        if len(data) == 1:
            return ModbusFrame(address, function, "exception", {"code": data[0]})
    elif function in BIT_READS | REGISTER_READS:
        if len(data) == 4:
            start, count = struct.unpack(">HH", data)
            return ModbusFrame(address, function, "request", {"start": start, "count": count})
        if data and data[0] == len(data) - 1:
            payload = data[1:]
            if function in BIT_READS:
                return ModbusFrame(address, function, "response", {"bits": unpack_bits(payload)})
            if len(payload) % 2 == 0:
                values = list(struct.unpack(f">{len(payload) // 2}H", payload))
                return ModbusFrame(address, function, "response", {"values": values})
    elif function in (WRITE_SINGLE_COIL, WRITE_SINGLE_REGISTER):
        if len(data) == 4:
            target, value = struct.unpack(">HH", data)
            if function == WRITE_SINGLE_COIL:
                fields: dict[str, object] = {"coil": target, "on": value == 0xFF00}
            else:
                fields = {"register": target, "value": value}
            return ModbusFrame(address, function, "request", fields)
    elif function in (WRITE_MULTIPLE_COILS, WRITE_MULTIPLE_REGISTERS):
        if len(data) == 4:
            start, count = struct.unpack(">HH", data)
            return ModbusFrame(address, function, "response", {"start": start, "count": count})
        if len(data) >= 5 and data[4] == len(data) - 5:
            start, count = struct.unpack(">HH", data[:4])
            payload = data[5:]
            if function == WRITE_MULTIPLE_COILS:
                bits = unpack_bits(payload, count)
                return ModbusFrame(
                    address, function, "request", {"start": start, "count": count, "bits": bits}
                )
            if len(payload) == 2 * count:
                values = list(struct.unpack(f">{count}H", payload))
                return ModbusFrame(
                    address, function, "request", {"start": start, "count": count, "values": values}
                )
    return ModbusFrame(address, function, "unknown", {"data": data.hex(" ")})
