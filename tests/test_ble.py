"""Tests for the BLE notification framing."""

from midisuite import protocol
from midisuite.transport import extract_packet

NAME_REPLY = bytes.fromhex(
    "00 59 11 1b 00 00 53 4d 43 2d 4d 69 78 65 72 5f 30 30 37 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 f4"
)
READ_REPLY = bytes.fromhex("00 59 23 09 00 00 04 00 00 00 00 01 00 00 01 f9")


def test_waits_for_complete_packet():
    buffer = bytearray(NAME_REPLY[:10])
    assert extract_packet(buffer) is None
    buffer.extend(NAME_REPLY[10:])
    assert extract_packet(buffer) == NAME_REPLY
    assert buffer == b""


def test_multiple_packets_are_queued():
    buffer = bytearray(NAME_REPLY + READ_REPLY)
    assert extract_packet(buffer) == NAME_REPLY
    assert extract_packet(buffer) == READ_REPLY
    assert extract_packet(buffer) is None


def test_skips_leading_noise():
    buffer = bytearray(b"\xff\x12" + READ_REPLY)
    assert extract_packet(buffer) == READ_REPLY


def test_skips_bad_checksum():
    broken = bytearray(READ_REPLY)
    broken[-1] ^= 0xFF
    buffer = bytearray(broken + READ_REPLY)
    assert extract_packet(buffer) == READ_REPLY


def test_expect_filters_short_packets():
    buffer = bytearray(READ_REPLY)
    assert extract_packet(buffer, expect=100) is None
    assert len(buffer) == 0


def test_reply_parses():
    packet = protocol.Packet.parse(NAME_REPLY)
    assert packet.msg_type == protocol.MSG_NAME
    assert packet.payload.decode("utf-8").rstrip("\x00") == "SMC-Mixer_007"
