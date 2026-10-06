"""Faulty frames for fault injection."""

from typing import Literal

FaultKind = Literal["bad_crc", "truncated", "extended", "bad_parity"]
FAULT_KINDS: tuple[FaultKind, ...] = ("bad_crc", "truncated", "extended", "bad_parity")


def corrupt_crc(frame: bytes) -> bytes:
    if len(frame) < 3:
        raise ValueError("frame is too short to have a CRC")
    return frame[:-2] + bytes((frame[-2] ^ 0xFF, frame[-1]))


def truncate(frame: bytes, count: int = 1) -> bytes:
    if not 0 < count < len(frame):
        raise ValueError(f"cannot remove {count} of {len(frame)} bytes")
    return frame[:-count]


def extend(frame: bytes, extra: bytes = b"\xff") -> bytes:
    if not extra:
        raise ValueError("extra bytes must not be empty")
    return frame + extra


def wrong_parity(parity: str) -> str:
    """A parity setting that makes the receiver see parity or framing errors."""
    return {"N": "E", "E": "O", "O": "E"}[parity]
