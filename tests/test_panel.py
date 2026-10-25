"""Tests for the schematic panel's button marks."""

from __future__ import annotations

from midisuite.devices.smc_mixer import BUTTON_COUNT
from midisuite.ui.panel import (
    STRIP_BUTTON_STYLES,
    TRANSPORT_START,
    TRANSPORT_STYLES,
    button_caption,
)

STRIP_MARKS = ["M", "S", "R", "■"]
TRANSPORT_NAMES = [
    "Play",
    "Pause",
    "Record",
    "Rewind",
    "Fast forward",
    "Previous",
    "Next",
    "Up",
    "Down",
    "Left",
    "Right",
]


def test_strip_button_marks():
    assert [mark for mark, _ in STRIP_BUTTON_STYLES] == ["M", "S", "R", "square"]
    for strip in range(8):
        for row, mark in enumerate(STRIP_MARKS):
            index = strip * 4 + row
            assert button_caption(index) == f"Strip {strip + 1} · {mark}"


def test_transport_button_order():
    names = [name for name, _ in TRANSPORT_STYLES]
    assert names == [
        "play",
        "pause",
        "record",
        "rewind",
        "fastforward",
        "previous",
        "next",
        "up",
        "down",
        "left",
        "right",
    ]
    assert len(TRANSPORT_STYLES) == BUTTON_COUNT - TRANSPORT_START
    for offset, name in enumerate(TRANSPORT_NAMES):
        index = TRANSPORT_START + offset
        assert button_caption(index) == f"Transport · {name}"
