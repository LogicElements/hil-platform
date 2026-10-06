import pytest

from hil.comm import modbus
from hil.comm.faults import FAULT_KINDS, corrupt_crc, extend, truncate, wrong_parity
from hil.comm.framing import split_frames

FRAME = modbus.read_request(1, 3, 0, 1)


def test_corrupt_crc():
    bad = corrupt_crc(FRAME)
    assert len(bad) == len(FRAME)
    assert bad[:-2] == FRAME[:-2]
    assert not modbus.crc_ok(bad)


def test_truncate_and_extend():
    assert truncate(FRAME) == FRAME[:-1]
    assert truncate(FRAME, 3) == FRAME[:-3]
    longer = extend(FRAME)
    assert longer == FRAME + bytes([0xFF])
    frames = split_frames(longer, t=0.0)
    assert frames[0].raw == FRAME
    assert frames[1].raw == bytes([0xFF])
    assert frames[1].error is not None


@pytest.mark.parametrize("count", [0, len(FRAME)])
def test_truncate_rejects_bad_count(count):
    with pytest.raises(ValueError):
        truncate(FRAME, count)


def test_extend_needs_bytes():
    with pytest.raises(ValueError):
        extend(FRAME, b"")


def test_wrong_parity():
    assert wrong_parity("N") == "E"
    assert wrong_parity("E") == "O"
    assert wrong_parity("O") == "E"
    assert FAULT_KINDS == ("bad_crc", "truncated", "extended", "bad_parity")
