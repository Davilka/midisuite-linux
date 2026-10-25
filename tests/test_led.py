"""Tests for the LED feedback message helpers."""

from __future__ import annotations

import pytest

from midisuite.devices.smc_mixer import SmcMixer
from midisuite.led import (
    button_led_mode,
    button_led_note,
    note_off,
    note_on,
    pitch_bend,
    pitch_bend_7bit,
)


def test_note_on_off():
    assert note_on(1, 16) == b"\x90\x10\x7f"
    assert note_off(1, 16) == b"\x90\x10\x00"
    assert note_on(16, 0, 0) == b"\x9f\x00\x00"
    assert note_off(16, 127) == b"\x9f\x7f\x00"


def test_note_validation():
    with pytest.raises(ValueError):
        note_on(0, 0)
    with pytest.raises(ValueError):
        note_on(17, 0)
    with pytest.raises(ValueError):
        note_on(1, 128)
    with pytest.raises(ValueError):
        note_on(1, 0, 128)


def test_pitch_bend():
    assert pitch_bend_7bit(1, 0) == b"\xe0\x00\x00"
    assert pitch_bend_7bit(1, 127) == b"\xe0\x00\x7f"
    assert pitch_bend_7bit(16, 64) == b"\xef\x00\x40"
    assert pitch_bend(1, 0) == b"\xe0\x00\x00"
    assert pitch_bend(1, 16383) == b"\xe0\x7f\x7f"
    assert pitch_bend(2, 8192) == b"\xe1\x00\x40"
    with pytest.raises(ValueError):
        pitch_bend(1, 16384)
    with pytest.raises(ValueError):
        pitch_bend_7bit(1, 128)


def test_button_led_semantics():
    mixer = SmcMixer.default()
    button = mixer.preset(0).button(0)
    assert button.led == 0xFF
    assert button_led_note(button) is None
    assert "follows the button" in button_led_mode(button)

    button.led = 16
    assert button_led_note(button) == 16
    assert "note 16" in button_led_mode(button)

    button.led = 0
    assert button_led_note(button) == 0

    button.led = 0x80
    assert button_led_note(button) is None
    assert "custom" in button_led_mode(button)
