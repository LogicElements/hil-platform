import random
import time

from hil.comm import modbus
from hil.comm.framing import (
    MAX_FRAME,
    NO_FRAME_ERROR,
    FrameSplitter,
    frame_length,
    split_frames,
)

REQUEST = modbus.read_request(1, 3, 0, 2)
RESPONSE = modbus.with_crc(bytes([1, 3, 4, 0, 1, 0, 2]))


def test_frame_length():
    assert frame_length(REQUEST) == len(REQUEST)
    assert frame_length(REQUEST + RESPONSE) == len(REQUEST)
    assert frame_length(REQUEST + RESPONSE, len(REQUEST)) == len(RESPONSE)
    assert frame_length(b"\x01\x02\x03") is None
    assert frame_length(REQUEST[:-1]) is None


def test_back_to_back_frames_in_one_chunk():
    frames = split_frames(REQUEST + RESPONSE, t=1.0)
    assert [f.raw for f in frames] == [REQUEST, RESPONSE]
    assert [f.decoded.kind for f in frames] == ["request", "response"]
    assert all(f.error is None and f.t == 1.0 for f in frames)


def test_garbage_then_valid_frame():
    splitter = FrameSplitter(gap_s=0.002)
    assert splitter.feed(b"\x01\x02\x03", t=0.0) == []
    frames = splitter.feed(REQUEST, t=0.010)
    assert len(frames) == 1
    assert frames[0].raw == b"\x01\x02\x03"
    assert frames[0].error == NO_FRAME_ERROR
    assert frames[0].decoded is None
    later = splitter.poll(t=0.020)
    assert [f.raw for f in later] == [REQUEST]
    assert later[0].t == 0.010


def test_chunks_within_gap_form_one_burst():
    splitter = FrameSplitter(gap_s=0.002)
    assert splitter.feed(REQUEST[:3], t=0.0) == []
    assert splitter.feed(REQUEST[3:], t=0.001) == []
    assert splitter.poll(t=0.0025) == []
    frames = splitter.poll(t=0.004)
    assert [f.raw for f in frames] == [REQUEST]
    assert frames[0].t == 0.0


def test_incomplete_frame_is_an_error_after_gap():
    splitter = FrameSplitter(gap_s=0.002)
    splitter.feed(REQUEST[:-1], t=0.0)
    frames = splitter.poll(t=0.01)
    assert frames[0].error == NO_FRAME_ERROR


def test_flush_and_max_burst():
    splitter = FrameSplitter(gap_s=1.0, max_burst=16)
    assert splitter.feed(REQUEST, t=0.0) == []
    frames = splitter.feed(RESPONSE + b"\xff" * 10, t=0.0)
    assert [f.raw for f in frames[:2]] == [REQUEST, RESPONSE]
    assert frames[2].error == NO_FRAME_ERROR
    assert splitter.flush() == []


def test_to_record():
    frame = split_frames(REQUEST, t=5.0)[0]
    record = frame.to_record(0.25)
    assert record["t"] == 0.25
    assert record["raw"] == REQUEST.hex(" ")
    assert record["decoded"]["kind"] == "request"
    assert record["error"] is None


def _request_ending_in_zero():
    for start in range(65536):
        frame = modbus.read_request(1, 3, start, 1)
        if frame[-1] == 0:
            return frame
    raise AssertionError("no request with CRC high byte 0x00 found")


def test_frame_ending_in_zero_is_not_truncated():
    # frame minus its trailing 0x00 has a valid CRC as well
    frame = _request_ending_in_zero()
    assert modbus.crc_ok(frame[:-1])
    assert frame_length(frame) == len(frame)
    frames = split_frames(frame, t=0.0)
    assert [f.raw for f in frames] == [frame]
    assert frames[0].error is None


def test_frame_ending_in_zero_followed_by_broadcast():
    frame = _request_ending_in_zero()
    broadcast = modbus.write_register_request(0, 7, 100)
    frames = split_frames(frame + broadcast, t=0.0)
    assert [f.raw for f in frames] == [frame, broadcast]
    assert all(f.error is None for f in frames)


def test_frame_ending_in_zero_followed_by_request():
    frame = _request_ending_in_zero()
    frames = split_frames(frame + REQUEST, t=0.0)
    assert [f.raw for f in frames] == [frame, REQUEST]
    assert all(f.error is None for f in frames)


def test_run_of_zeros_after_frame_is_an_error():
    # a genuine frame takes at most two 0x00 bytes (both CRC bytes zero)
    frame = modbus.read_request(2, 3, 0, 1)
    assert frame[-1] != 0
    frames = split_frames(frame + bytes(5), t=0.0)
    assert [f.raw for f in frames] == [frame, bytes(5)]
    assert frames[0].error is None
    assert frames[1].error == NO_FRAME_ERROR


def test_stray_byte_before_exchange():
    frames = split_frames(b"\x55" + REQUEST + RESPONSE, t=0.0)
    assert [f.raw for f in frames] == [b"\x55", REQUEST, RESPONSE]
    assert [f.error for f in frames] == [NO_FRAME_ERROR, None, None]


def test_truncated_request_before_exchange():
    frames = split_frames(REQUEST[:-2] + REQUEST + RESPONSE, t=0.0)
    assert [f.raw for f in frames] == [REQUEST[:-2], REQUEST, RESPONSE]
    assert [f.error for f in frames] == [NO_FRAME_ERROR, None, None]


def test_pure_garbage_is_one_error_frame():
    garbage = random.Random(5).randbytes(4 * MAX_FRAME)
    assert frame_length(garbage) is None
    start = time.perf_counter()
    frames = split_frames(garbage, t=0.0)
    elapsed = time.perf_counter() - start
    assert [f.raw for f in frames] == [garbage]
    assert frames[0].error == NO_FRAME_ERROR
    assert elapsed < 1.0


def _reference_split(data):
    # brute force: the first position after an error from which the rest parses cleanly
    def clean(start):
        while start < len(data):
            length = frame_length(data, start)
            if length is None:
                return False
            start += length
        return True

    raws, pos = [], 0
    while pos < len(data):
        length = frame_length(data, pos)
        if length is None:
            length = next((p for p in range(pos + 1, len(data)) if clean(p)), len(data)) - pos
        raws.append(data[pos : pos + length])
        pos += length
    return raws


def test_resync_matches_brute_force():
    rnd = random.Random(11)
    frames = [
        REQUEST,
        RESPONSE,
        _request_ending_in_zero(),
        modbus.write_register_request(0, 7, 100),
        modbus.with_crc(bytes([2, 0x83, 2])),
    ]
    for _ in range(300):
        parts = []
        for _ in range(rnd.randrange(1, 6)):
            choice = rnd.random()
            frame = rnd.choice(frames)
            if choice < 0.2:
                parts.append(rnd.randbytes(rnd.randrange(1, 6)))
            elif choice < 0.3:
                parts.append(frame[: rnd.randrange(1, len(frame))])
            elif choice < 0.4:
                parts.append(bytes(rnd.randrange(1, 4)))
            else:
                parts.append(frame)
        data = b"".join(parts)
        assert [f.raw for f in split_frames(data, t=0.0)] == _reference_split(data)


def test_bit_read_response_with_three_bytes_after_request():
    request = modbus.read_request(1, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    splitter = FrameSplitter(gap_s=0.002)
    frames = splitter.feed(request, 0.0)
    frames += splitter.poll(0.01)
    frames += splitter.feed(response, 0.02)
    frames += splitter.poll(0.03)
    assert [f.decoded.kind for f in frames if f.decoded] == ["request", "response"]


def test_split_frames_passes_previous_frame():
    request = modbus.read_request(1, modbus.READ_COILS, 0, 20)
    response = modbus.with_crc(bytes((1, 1, 3, 0x01, 0x02, 0x03)))
    frames = split_frames(request + response, t=0.0)
    assert [f.decoded.kind for f in frames if f.decoded] == ["request", "response"]
