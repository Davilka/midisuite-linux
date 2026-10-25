"""Wire protocol of the M-VAVE / SINCO SMC-Mixer.

Recovered from ``Midi Suite.exe`` (Flutter, ``package:musical_instruments``)
and verified against a real SMC-Mixer over USB MIDI.

Raw packet (8-bit):

    00 59 | type | len24le | payload ... | checksum

* ``00 59``  fixed header
* ``type``   message type (see ``MSG_*``)
* ``len24le`` length of ``payload`` (3 bytes, little endian)
* ``checksum`` ``~sum(packet[6:]) & 0xFF`` (sum starts *after* the length field)

The checksum covers the type, the length field and the payload, i.e. every
byte of the packet except the header and the checksum itself.

Transports
----------
USB MIDI: the packet is 8-to-7 bit packed (base-128) and wrapped into a
standard system exclusive message::

    F0 <base128(packet)> F7

BLE GATT: the packet is written as-is to characteristic ``AE41``; replies
arrive as notifications on ``AE42`` (service ``AE40``).
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER = b"\x00\x59"

MSG_ACK = 0x00
MSG_NAME = 0x11
MSG_ERASE = 0x21
MSG_WRITE = 0x22
MSG_READ = 0x23

MIN_PACKET = 7


# --------------------------------------------------------------------------
# 8 <-> 7 bit packing
# --------------------------------------------------------------------------
def base128_encode(data: bytes) -> bytes:
    """Pack an 8-bit byte string into a stream of 7-bit values.

    Implements the continuous bit stream used by Cuvave/M-VAVE firmware
    (LSB first, 7 bits per output byte, final partial byte emitted).
    """
    out = bytearray()
    bits = 0
    acc = 0
    for byte in data:
        acc |= byte << bits
        bits += 8
        while bits >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            bits -= 7
    # The firmware (and the reference Cuvave implementation) always emits the
    # final partial byte, even when no bits are left.
    out.append(acc & 0x7F)
    return bytes(out)


def base128_decode(data: bytes) -> bytes:
    """Inverse of :func:`base128_encode`."""
    out = bytearray()
    bit_num = 0
    last = 0
    for byte in data:
        mask = (0xFFFFFFFF >> (32 - bit_num)) if bit_num else 0
        acc = byte & mask
        if bit_num:
            out.append(((last & 0x7F) | (acc << (8 - bit_num))) & 0xFF)
        last = byte >> bit_num
        bit_num = (bit_num + 1) % 8
    if last:
        out.append(last)
    return bytes(out)


def to_sysex(packet: bytes) -> bytes:
    """Wrap a raw packet into a MIDI system exclusive message."""
    return b"\xf0" + base128_encode(packet) + b"\xf7"


def from_sysex(sysex: bytes) -> bytes:
    """Unwrap a system exclusive message into a raw packet."""
    if not sysex or sysex[0] != 0xF0 or sysex[-1] != 0xF7:
        raise ValueError("not a system exclusive message")
    return base128_decode(sysex[1:-1])


# --------------------------------------------------------------------------
# Packets
# --------------------------------------------------------------------------
def checksum(packet: bytes) -> int:
    """Return the checksum byte for a packet without its trailing checksum."""
    return (~sum(packet[6:])) & 0xFF


def build(msg_type: int, payload: bytes = b"") -> bytes:
    """Build a raw packet with checksum."""
    packet = HEADER + bytes([msg_type]) + len(payload).to_bytes(3, "little") + payload
    return packet + bytes([checksum(packet)])


def build_read(block: int, addr: int, length: int) -> bytes:
    payload = bytes([block]) + addr.to_bytes(4, "little") + length.to_bytes(3, "little")
    return build(MSG_READ, payload)


def build_write(block: int, addr: int, data: bytes) -> bytes:
    payload = (
        bytes([block])
        + addr.to_bytes(4, "little")
        + len(data).to_bytes(3, "little")
        + data
    )
    return build(MSG_WRITE, payload)


def build_erase(block: int, addr: int) -> bytes:
    return build(MSG_ERASE, bytes([block]) + addr.to_bytes(4, "little"))


def build_name_request() -> bytes:
    return build(MSG_NAME)


@dataclass
class Packet:
    """A decoded raw packet."""

    msg_type: int
    payload: bytes

    @classmethod
    def parse(cls, packet: bytes) -> Packet:
        if len(packet) < MIN_PACKET:
            raise ValueError(f"packet too short: {packet.hex(' ')}")
        if packet[:2] != HEADER:
            raise ValueError(f"bad header: {packet[:2].hex(' ')}")
        length = int.from_bytes(packet[3:6], "little")
        payload = packet[6 : 6 + length]
        if len(payload) != length:
            raise ValueError(
                f"truncated packet: want {length} payload bytes, got {len(payload)}"
            )
        expected = checksum(packet[: 6 + length])
        actual = packet[6 + length] if len(packet) > 6 + length else None
        if actual != expected:
            raise ValueError(
                f"bad checksum: expected {expected:02x}, got "
                f"{'none' if actual is None else format(actual, '02x')}"
            )
        return cls(packet[2], payload)

    @property
    def packet_length(self) -> int:
        """Total packet length including checksum."""
        return 7 + len(self.payload)


def parse_memory_payload(payload: bytes) -> tuple[int, int, int, bytes]:
    """Split a read/write payload into ``(block, addr, length, data)``."""
    if len(payload) < 8:
        raise ValueError(f"memory payload too short: {payload.hex(' ')}")
    block = payload[0]
    addr = int.from_bytes(payload[1:5], "little")
    length = int.from_bytes(payload[5:8], "little")
    return block, addr, length, payload[8:]
