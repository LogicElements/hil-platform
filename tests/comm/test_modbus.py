import pytest

from hil.comm import modbus


def test_crc_known_values():
    assert modbus.crc16(b"123456789") == 0x4B37
    assert modbus.with_crc(bytes.fromhex("01 03 00 00 00 0A")) == bytes.fromhex(
        "01 03 00 00 00 0A C5 CD"
    )
    assert modbus.with_crc(bytes.fromhex("11 06 00 01 00 03")) == bytes.fromhex(
        "11 06 00 01 00 03 9A 9B"
    )


def test_crc_ok():
    frame = modbus.with_crc(b"\x01\x03\x00\x00\x00\x01")
    assert modbus.crc_ok(frame)
    assert not modbus.crc_ok(frame[:-1] + bytes([frame[-1] ^ 1]))
    assert not modbus.crc_ok(b"\x01\x03\x00")


def test_read_request():
    assert modbus.read_request(1, 3, 0, 10) == bytes.fromhex("01 03 00 00 00 0A C5 CD")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((248, 3, 0, 1), "address"),
        ((1, 3, 0, 0), "count"),
        ((1, 3, 0, 126), "count"),
        ((1, 1, 0, 2001), "count"),
        ((1, 6, 0, 1), "not a read function"),
    ],
)
def test_read_request_validation(args, message):
    with pytest.raises(ValueError, match=message):
        modbus.read_request(*args)


def test_write_builders():
    assert modbus.write_register_request(0x11, 1, 3) == bytes.fromhex("11 06 00 01 00 03 9A 9B")
    coil = modbus.write_coil_request(1, 2, True)
    assert coil[:6] == bytes.fromhex("01 05 00 02 FF 00")
    registers = modbus.write_registers_request(1, 16, [1, 2])
    assert registers[:-2] == bytes.fromhex("01 10 00 10 00 02 04 00 01 00 02")
    coils = modbus.write_coils_request(1, 0, [True, False, True])
    assert coils[:-2] == bytes.fromhex("01 0F 00 00 00 03 01 05")
    with pytest.raises(ValueError, match="value"):
        modbus.write_register_request(1, 0, 0x10000)


def test_bits_round_trip():
    values = [True, False, False, True, True, False, False, False, True]
    packed = modbus.pack_bits(values)
    assert packed == bytes([0b00011001, 0b00000001])
    assert modbus.unpack_bits(packed, len(values)) == values


def test_decode_read_request_and_responses():
    request = modbus.decode(modbus.read_request(1, 3, 5, 2))
    assert (request.kind, request.fields) == ("request", {"start": 5, "count": 2})
    registers = modbus.decode(modbus.with_crc(bytes([1, 3, 4, 0, 42, 1, 0])))
    assert (registers.kind, registers.fields) == ("response", {"values": [42, 256]})
    bits = modbus.decode(modbus.with_crc(bytes([1, 1, 1, 0b101])))
    assert bits.kind == "response"
    assert bits.fields["bits"][:3] == [True, False, True]


def test_decode_exception_and_writes():
    exception = modbus.decode(modbus.with_crc(bytes([1, 0x83, 2])))
    assert (exception.kind, exception.fields) == ("exception", {"code": 2})
    single = modbus.decode(modbus.write_register_request(1, 7, 99))
    assert single.fields == {"register": 7, "value": 99}
    coil = modbus.decode(modbus.write_coil_request(1, 3, True))
    assert coil.fields == {"coil": 3, "on": True}
    multiple = modbus.decode(modbus.write_registers_request(1, 16, [1, 2]))
    assert (multiple.kind, multiple.fields) == (
        "request",
        {"start": 16, "count": 2, "values": [1, 2]},
    )
    answer = modbus.decode(modbus.with_crc(bytes.fromhex("01 10 00 10 00 02")))
    assert (answer.kind, answer.fields) == ("response", {"start": 16, "count": 2})


def test_decode_unknown_and_bad_crc():
    unknown = modbus.decode(modbus.with_crc(bytes([1, 0x2B, 0x0E, 1])))
    assert unknown.kind == "unknown"
    assert unknown.to_dict()["address"] == 1
    with pytest.raises(ValueError, match="bad CRC"):
        modbus.decode(b"\x01\x03\x00\x00\x00\x01\x00\x00")
