"""Helpers for the SMC-Mixer's MIDI LED feedback.

Button LEDs have two modes, stored in byte 70 of the button record:

* ``0xFF`` – the LED follows the button itself (local toggle/momentary state);
* ``0..127`` – the LED is controlled by incoming Note On/Off messages with
  that note number.

The eight LEDs under the knobs are fader soft-takeover indicators.  They are
driven by Pitch Bend on the fader's channel: a value different from the
physical fader makes the LED blink, a matching value turns it off.  These
indicators are only active while the DAW slot (preset 1) is selected.
"""

from __future__ import annotations

from .devices.smc_mixer import ButtonSlot

MAX_NOTE = 127
MAX_PITCH_BEND = 16383


def _channel(value: int) -> int:
    if not 1 <= value <= 16:
        raise ValueError(f"channel must be 1…16, not {value}")
    return value - 1


def _data(value: int, maximum: int, name: str) -> int:
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be 0…{maximum}, not {value}")
    return value


def note_on(channel: int, note: int, velocity: int = 127) -> bytes:
    """Note On on a 1-based channel."""
    return bytes(
        [
            0x90 | _channel(channel),
            _data(note, MAX_NOTE, "note"),
            _data(velocity, MAX_NOTE, "velocity"),
        ]
    )


def note_off(channel: int, note: int) -> bytes:
    """Note Off as Note On with velocity 0 (the format the device itself uses)."""
    return note_on(channel, note, 0)


def pitch_bend_7bit(channel: int, value: int) -> bytes:
    """Pitch Bend with the value in the MSB and an LSB of 0.

    The SMC-Mixer faders send exactly this form: ``E0 00 00`` … ``E0 00 7F``.
    """
    return bytes(
        [0xE0 | _channel(channel), 0x00, _data(value, MAX_NOTE, "value")]
    )


def pitch_bend(channel: int, value: int) -> bytes:
    """Full 14-bit Pitch Bend."""
    value = _data(value, MAX_PITCH_BEND, "value")
    return bytes(
        [0xE0 | _channel(channel), value & 0x7F, (value >> 7) & 0x7F]
    )


def button_led_note(slot: ButtonSlot) -> int | None:
    """Return the note that controls a button LED, or ``None`` for 0xFF."""
    value = slot.led
    if value == 0xFF or value > MAX_NOTE:
        return None
    return value


def button_led_mode(slot: ButtonSlot) -> str:
    """Human-readable description of the button's LED setting."""
    note = button_led_note(slot)
    if note is None:
        if slot.led == 0xFF:
            return "follows the button (0xFF)"
        return f"custom value 0x{slot.led:02X} (no note feedback)"
    return f"note {note} (incoming Note On/Off)"
