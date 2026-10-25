"""Tests for the SMC-Mixer wire protocol."""

import pytest

from midisuite import protocol


def test_base128_roundtrip():
    for data in (b"", b"\x00", b"\xff", bytes(range(256)), b"\xf0\x00\xb2\x22"):
        assert protocol.base128_decode(protocol.base128_encode(data)) == data


def test_name_request_vector():
    packet = protocol.build_name_request()
    assert packet == bytes.fromhex("00 59 11 00 00 00 FF")
    # Captured from the device / the official application on the wire.
    assert (
        protocol.to_sysex(packet).hex(" ")
        == "f0 00 32 45 00 00 00 40 7f 00 f7"
    )


def test_read_request_vector():
    packet = protocol.build_read(4, 0, 1)
    assert packet == bytes.fromhex("00 59 23 08 00 00 04 00 00 00 00 01 00 00 FA")
    assert (
        protocol.to_sysex(packet).hex(" ")
        == "f0 00 32 0d 41 00 00 00 02 00 00 00 00 10 00 00 00 7a 01 f7"
    )


def test_parse_read_reply():
    raw = bytes.fromhex("00 59 23 09 00 00 04 00 00 00 00 01 00 00 01 F9")
    packet = protocol.Packet.parse(raw)
    block, addr, length, data = protocol.parse_memory_payload(packet.payload)
    assert (block, addr, length, data) == (4, 0, 1, b"\x01")


def test_parse_name_reply():
    # Response captured from a real SMC-Mixer (firmware 007).
    sysex = bytes.fromhex(
        "f0 00 32 45 58 01 00 40 29 4d 06 35 69 14 0d 5e 32 72 3e 41 01 "
        "73 06 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3d f7"
    )
    packet = protocol.Packet.parse(protocol.from_sysex(sysex))
    assert packet.msg_type == protocol.MSG_NAME
    assert packet.payload.decode("utf-8").rstrip("\x00").startswith("SMC-Mixer_")


def test_bad_checksum():
    raw = bytearray.fromhex("00 59 23 09 00 00 04 00 00 00 00 01 00 00 01 F9")
    raw[-1] ^= 0xFF
    with pytest.raises(ValueError):
        protocol.Packet.parse(bytes(raw))
