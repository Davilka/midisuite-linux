"""Tests for shared transport helpers."""

from midisuite import protocol
from midisuite.transport import BaseTransport


class RecordingTransport(BaseTransport):
    """Collect packets instead of opening a real MIDI/BLE link."""

    def __init__(self):
        super().__init__()
        self.packets: list[tuple[bytes, int | None]] = []

    def send(self, packet: bytes, expect: int | None = None) -> bytes:
        self.packets.append((packet, expect))
        return protocol.build(protocol.MSG_ACK, b"\x01")

    def close(self) -> None:
        pass


def test_commit_sends_zero_length_write():
    transport = RecordingTransport()
    transport.commit(5)
    assert transport.packets == [
        (protocol.build_write(5, 0, b""), None),
    ]
