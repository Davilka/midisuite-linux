"""Tests for the SMC-Mixer memory layout."""

import pytest

from midisuite.devices.smc_mixer import (
    BUTTON_COUNT,
    BUTTON_SIZE,
    KNOB_COUNT,
    KNOB_SIZE,
    PRESET_SIZE,
    SLIDER_COUNT,
    SLIDER_SIZE,
    Preset,
    SmcMixer,
    default_preset,
    default_user_block,
)


def test_layout_arithmetic():
    assert PRESET_SIZE == BUTTON_COUNT * BUTTON_SIZE + KNOB_COUNT * KNOB_SIZE + SLIDER_COUNT * SLIDER_SIZE
    assert len(default_user_block()) == 2 * PRESET_SIZE


def test_defaults_match_layout():
    mixer = SmcMixer.default()
    button = mixer.preset(0).button(0)
    assert button.type == 1
    assert button.channel == 0
    assert button.data1 == 20
    assert (button.value_off, button.value_on) == (0, 127)
    assert button.led == 0xFF
    assert button.sysex == b""

    slider = mixer.preset(0).slider(0)
    assert (slider.type, slider.channel, slider.data1) == (0, 0, 40)
    assert (slider.minimum, slider.maximum) == (0, 127)

    knob = mixer.preset(0).knob(0)
    assert (knob.type, knob.curve, knob.channel, knob.data1) == (0, 1, 0, 16)
    assert (knob.minimum, knob.maximum) == (0, 127)


def test_roundtrip_preset_dict():
    preset = Preset(default_preset())
    clone = Preset.from_dict(preset.to_dict())
    assert clone.to_bytes() == preset.to_bytes()


def test_roundtrip_json():
    mixer = SmcMixer.default()
    clone = SmcMixer.from_json(mixer.to_json())
    assert bytes(clone.user) == bytes(mixer.user)


def test_edit_button_keeps_other_bytes():
    mixer = SmcMixer.default()
    preset = mixer.preset(0)
    before = preset.to_bytes()
    preset.button(3).channel = 9
    after = preset.to_bytes()
    assert len(after) == len(before)
    assert sum(1 for a, b in zip(before, after) if a != b) == 1


def test_active_preset_byte():
    mixer = SmcMixer.default()
    assert mixer.active_preset == 0
    mixer.set_active_preset(1)
    assert mixer.active_preset == 1
    assert mixer.globals[0] == 1
    mixer.globals[0] = 9
    assert mixer.active_preset is None
    with pytest.raises(IndexError):
        mixer.set_active_preset(2)
