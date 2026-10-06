"""Splitting of received bytes into Modbus RTU frames."""

from dataclasses import dataclass

from hil.comm.modbus import CRC_TABLE, ModbusFrame, decode

MIN_FRAME = 4
MAX_FRAME = 256
# 0x00 bytes a frame can take after its shortest CRC match (both CRC bytes zero)
_MAX_ZERO_EXTENSION = 2
NO_FRAME_ERROR = "no valid Modbus RTU frame (bad CRC or incomplete frame)"


@dataclass(frozen=True)
class Frame:
    """Bytes seen on the bus: ``decoded`` for a valid frame, ``error`` otherwise."""

    t: float
    raw: bytes
    decoded: ModbusFrame | None
    error: str | None

    def to_record(self, t: float) -> dict[str, object]:
        """JSON record with ``t`` (e.g. relative to the start of the test) as time stamp."""
        return {
            "t": round(t, 6),
            "raw": self.raw.hex(" "),
            "decoded": None if self.decoded is None else self.decoded.to_dict(),
            "error": self.error,
        }


def _shortest_length(data: bytes, start: int) -> int | None:
    """Length of the shortest frame with a valid CRC at ``data[start:]``, or None."""
    crc = 0xFFFF
    table = CRC_TABLE  # inlined CRC step: this loop dominates the cost of resync
    end = min(len(data), start + MAX_FRAME)
    for pos in range(start, end - 1):
        # crc covers data[start:pos]; the candidate frame is data[start:pos + 2]
        if pos - start >= MIN_FRAME - 2 and crc == data[pos] | (data[pos + 1] << 8):
            return pos - start + 2
        crc = (crc >> 8) ^ table[(crc ^ data[pos]) & 0xFF]
    return None


def frame_length(data: bytes, start: int = 0) -> int | None:
    """Length of the frame with a valid CRC at ``data[start:]``, or None.

    A CRC-valid frame followed by 0x00 has a valid CRC as well, so a frame whose CRC high
    byte is 0x00 also validates one byte short. A 0x00 after the shortest match therefore
    belongs to the frame unless a CRC-valid frame (e.g. a broadcast) starts at it. A frame
    takes at most two such bytes (both CRC bytes 0x00); a longer run of zeros is not CRC
    and is left out of the frame entirely.
    """
    shortest = _shortest_length(data, start)
    if shortest is None:
        return None

    def takes_zero(length: int) -> bool:
        return (
            length < MAX_FRAME
            and start + length < len(data)
            and data[start + length] == 0
            and _shortest_length(data, start + length) is None
        )

    length = shortest
    while length < shortest + _MAX_ZERO_EXTENSION and takes_zero(length):
        length += 1
    return shortest if takes_zero(length) else length


def _inverse_table() -> tuple[int, ...]:
    # the high bytes of the CRC table entries are all different
    inverse = [0] * 256
    for index, value in enumerate(CRC_TABLE):
        inverse[value >> 8] = index
    return tuple(inverse)


_CRC_INVERSE = _inverse_table()


def _crc_starts(data: bytes, end: int, lowest: int) -> list[int]:
    """Positions ``s >= lowest`` where ``data[s:end]`` is a frame with a valid CRC.

    Runs the CRC backwards from ``end``: the state is the one that leads to the residue 0
    of a valid frame at ``end``, so a frame starts where it equals the initial 0xFFFF.
    """
    starts = []
    state = 0
    table, inverse = CRC_TABLE, _CRC_INVERSE
    for pos in range(end - 1, max(lowest, end - MAX_FRAME) - 1, -1):
        index = inverse[state >> 8]
        state = ((state ^ table[index]) << 8) | (index ^ data[pos])
        if state == 0xFFFF and end - pos >= MIN_FRAME:
            starts.append(pos)
    return starts


def _resync(data: bytes, pos: int) -> int:
    """First position after ``pos`` from which ``data`` splits into valid frames to its end.

    Returns ``len(data)`` when there is none. Positions are decided from the end of the
    burst backwards: a frame can only start where a backward CRC pass from a position that
    splits cleanly (or up to two 0x00 bytes before one, see ``frame_length``) finds a CRC
    match, and only those candidates are checked with ``frame_length``. That keeps a
    garbage burst at O(n + MAX_FRAME) instead of a ``frame_length`` per position.
    """
    clean = {len(data)}
    candidates: set[int] = set()

    def mark(end: int) -> None:
        for extension in range(_MAX_ZERO_EXTENSION + 1):
            crc_end = end - extension
            if crc_end <= pos + 1 or any(data[crc_end:end]):
                break
            candidates.update(_crc_starts(data, crc_end, pos + 1))

    mark(len(data))
    first = len(data)
    for start in range(len(data) - 1, pos, -1):
        if start not in candidates:
            continue
        length = frame_length(data, start)
        if length is not None and start + length in clean:
            clean.add(start)
            first = start
            mark(start)
    return first


def split_frames(data: bytes, t: float) -> list[Frame]:
    """Split one burst into frames; bytes that form no valid frame become an error frame.

    After bytes that start no valid frame (a stray byte, a truncated frame), the error
    frame ends where the rest of the burst splits cleanly into valid frames to its end;
    when there is no such position, the rest of the burst is one error frame.
    """
    frames: list[Frame] = []
    pos = 0
    while pos < len(data):
        length = frame_length(data, pos)
        if length is None:
            resync = _resync(data, pos)
            frames.append(Frame(t, data[pos:resync], None, NO_FRAME_ERROR))
            pos = resync
            continue
        raw = data[pos : pos + length]
        frames.append(Frame(t, raw, decode(raw), None))
        pos += length
    return frames


class FrameSplitter:
    """Groups received chunks into bursts separated by silence and splits them into frames.

    Every frame of a burst carries the time stamp of the burst's first chunk. Frames
    that follow each other without a measurable gap are still separated by their CRC.
    """

    def __init__(self, gap_s: float, max_burst: int = 4 * MAX_FRAME) -> None:
        self.gap_s = gap_s
        self.max_burst = max_burst
        self._buffer = bytearray()
        self._first = 0.0
        self._last = 0.0

    def feed(self, data: bytes, t: float) -> list[Frame]:
        frames = self.poll(t)
        if data:
            if not self._buffer:
                self._first = t
            self._buffer.extend(data)
            self._last = t
            if len(self._buffer) >= self.max_burst:
                frames += self.flush()
        return frames

    def poll(self, t: float) -> list[Frame]:
        """Frames of a burst that has been followed by enough silence."""
        if self._buffer and t - self._last > self.gap_s:
            return self.flush()
        return []

    def flush(self) -> list[Frame]:
        if not self._buffer:
            return []
        data = bytes(self._buffer)
        self._buffer.clear()
        return split_frames(data, self._first)
