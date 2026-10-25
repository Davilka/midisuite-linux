"""SMC-Mixer memory model (independent implementation).

The layout is described in ``docs/protocol.md``; it was established by
observing the device behaviour and the bytes it stores, then verified by
round-tripping every field against real hardware.  No vendor code or assets
are used here.

User block (block 5) is 6282 bytes and holds two presets of 3141 bytes::

    3141 = 43 * 71   buttons
         +  8 * 6    knobs
         +  8 * 5    sliders
"""

from __future__ import annotations

import json
from dataclasses import dataclass

BLOCK_GLOBAL = 4
BLOCK_USER = 5

GLOBAL_SIZE = 128
USER_SIZE = 6282

PRESET_COUNT = 2
PRESET_SIZE = 3141

BUTTON_COUNT = 43
BUTTON_SIZE = 71

KNOB_COUNT = 8
KNOB_SIZE = 6

SLIDER_COUNT = 8
SLIDER_SIZE = 5

BUTTON_OFFSET = 0
KNOB_OFFSET = BUTTON_COUNT * BUTTON_SIZE  # 3053
SLIDER_OFFSET = KNOB_OFFSET + KNOB_COUNT * KNOB_SIZE  # 3101

#: Verified message modes (the byte is interpreted per control kind).
BUTTON_TYPES = {
    0: "CC (value 2 only)",
    1: "CC toggle",
    2: "CC momentary",
    3: "Program change + bank",
    4: "SysEx (raw bytes)",
    5: "Note",
    6: "SysEx (raw bytes)",
    7: "none",
    8: "none",
}
KNOB_TYPES = {
    0: "CC absolute",
    1: "Channel pressure",
    2: "Pitch bend",
    3: "CC relative / pulse",
}
FADER_TYPES = {
    0: "CC absolute",
    1: "Channel pressure",
    2: "Pitch bend",
    3: "none",
    4: "none",
}


#: Number of buttons that belong to the eight channel strips (the remaining
#: eleven are transport / mode buttons).
STRIP_BUTTON_COUNT = 32
TRANSPORT_BUTTONS = range(32, 43)


def default_preset() -> bytes:
    """A clean, self-generated default preset.

    This is *not* a copy of the vendor data: it is a sensible mapping built
    from the documented layout (toggle buttons on CC 20…62, absolute CC knobs
    on CC 16…23, absolute CC faders on CC 40…47, all LEDs enabled).
    """
    data = bytearray(PRESET_SIZE)
    for index in range(BUTTON_COUNT):
        offset = BUTTON_OFFSET + index * BUTTON_SIZE
        # 0…31: four buttons per strip (toggle), 32…42: transport (momentary)
        data[offset + 0] = 1 if index < 32 else 2
        data[offset + 1] = 0
        data[offset + 2] = 20 + index
        data[offset + 3] = 0
        data[offset + 4] = 127
        data[offset + 5] = 0
        data[offset + 70] = 0xFF  # LED feedback on
    for index in range(KNOB_COUNT):
        offset = KNOB_OFFSET + index * KNOB_SIZE
        data[offset : offset + 6] = bytes([0, 1, 0, 16 + index, 0, 127])
    for index in range(SLIDER_COUNT):
        offset = SLIDER_OFFSET + index * SLIDER_SIZE
        data[offset : offset + 5] = bytes([0, 0, 40 + index, 0, 127])
    return bytes(data)


def default_user_block() -> bytes:
    return default_preset() * PRESET_COUNT


def default_globals() -> bytes:
    return bytes(GLOBAL_SIZE)


@dataclass
class ButtonSlot:
    """71-byte button record.

    ``type`` selects the MIDI message (note, CC, program change, sysex, ...).
    ``sysex`` holds up to 64 bytes of a custom system exclusive message.
    """

    raw: memoryview

    @classmethod
    def empty(cls) -> ButtonSlot:
        return cls(memoryview(bytearray(BUTTON_SIZE)))

    @property
    def type(self) -> int:
        return self.raw[0]

    @type.setter
    def type(self, value: int) -> None:
        self.raw[0] = value & 0xFF

    @property
    def channel(self) -> int:
        return self.raw[1]

    @channel.setter
    def channel(self, value: int) -> None:
        self.raw[1] = value & 0xFF

    @property
    def data1(self) -> int:
        return self.raw[2]

    @data1.setter
    def data1(self, value: int) -> None:
        self.raw[2] = value & 0xFF

    @property
    def value_off(self) -> int:
        """Second value.

        CC toggle/momentary: release value.  Program change: bank LSB.
        CC type 0: the only value that is sent.  For notes it is ignored
        (the device always sends note-off velocity 0).
        """
        return self.raw[3]

    @value_off.setter
    def value_off(self, value: int) -> None:
        self.raw[3] = value & 0xFF

    @property
    def value_on(self) -> int:
        """First value: velocity, program number, or CC press value."""
        return self.raw[4]

    @value_on.setter
    def value_on(self, value: int) -> None:
        self.raw[4] = value & 0xFF

    # Backwards compatible aliases (used by older exports).
    data2 = property(lambda self: self.value_off, lambda self, v: setattr(self, "value_off", v))
    option = property(lambda self: self.value_on, lambda self, v: setattr(self, "value_on", v))

    @property
    def sysex(self) -> bytes:
        length = min(self.raw[5], 64)
        return bytes(self.raw[6 : 6 + length])

    @sysex.setter
    def sysex(self, value: bytes) -> None:
        if len(value) > 64:
            raise ValueError("SysEx payload is limited to 64 bytes")
        self.raw[5] = len(value)
        self.raw[6:70] = bytes(value).ljust(64, b"\x00")

    @property
    def led(self) -> int:
        """LED feedback setting (the "Led" field of the original editor).

        ``0xFF`` makes the LED follow the button itself (toggle latches,
        momentary follows the press).  A value 0…127 selects a **note
        number**: the LED is then controlled by incoming Note On/Off with
        that note (verified in a CC preset by setting the byte to 16 and
        sending note 16 on the button's channel).  Larger values have no
        observed note feedback.

        Writing the byte does not switch the LED on by itself: with ``0xFF``
        the firmware refreshes it on button events, while a note value only
        reacts to the matching incoming note.
        """
        return self.raw[70]

    @led.setter
    def led(self, value: int) -> None:
        self.raw[70] = value & 0xFF

    @property
    def led_note(self) -> int | None:
        """The note that controls this LED, or ``None`` when it follows the button."""
        return self.led if self.led <= 0x7F else None

    @property
    def led_enabled(self) -> bool:
        """True when the LED is driven locally by the button itself."""
        return self.led == 0xFF

    @led_enabled.setter
    def led_enabled(self, value: bool) -> None:
        self.led = 0xFF if value else 0x00

    # Backwards compatible alias.
    flag = property(lambda self: self.led, lambda self, v: setattr(self, "led", v))

    def describe(self) -> str:
        if self.sysex:
            return f"type={self.type} ch={self.channel + 1} sysex={self.sysex.hex(' ')}"
        return (
            f"type={self.type} ch={self.channel + 1} "
            f"d1={self.data1} v2={self.value_off} v1={self.value_on}"
        )


@dataclass
class KnobSlot:
    """6-byte encoder record: ``type, curve, channel, controller, min, max``.

    Measured behaviour: the encoder is continuous (no detents).  In absolute
    mode the controller value is ``round(position * max / 127)`` — the fifth
    byte scales the output and the fourth byte had no observable effect.
    ``curve`` (byte 1) is a response-speed/acceleration factor: 8 changes the
    value several times faster than 1 for the same rotation.
    """

    raw: memoryview

    @classmethod
    def empty(cls) -> KnobSlot:
        return cls(memoryview(bytearray(KNOB_SIZE)))

    @property
    def type(self) -> int:
        return self.raw[0]

    @type.setter
    def type(self, value: int) -> None:
        self.raw[0] = value & 0xFF

    @property
    def curve(self) -> int:
        return self.raw[1]

    @curve.setter
    def curve(self, value: int) -> None:
        self.raw[1] = value & 0xFF

    @property
    def channel(self) -> int:
        return self.raw[2]

    @channel.setter
    def channel(self, value: int) -> None:
        self.raw[2] = value & 0xFF

    @property
    def data1(self) -> int:
        return self.raw[3]

    @data1.setter
    def data1(self, value: int) -> None:
        self.raw[3] = value & 0xFF

    @property
    def minimum(self) -> int:
        """Fourth byte; no observable effect in absolute CC mode."""
        return self.raw[4]

    @minimum.setter
    def minimum(self, value: int) -> None:
        self.raw[4] = value & 0xFF

    @property
    def maximum(self) -> int:
        """Fifth byte; scales the absolute value (0…max)."""
        return self.raw[5]

    @maximum.setter
    def maximum(self, value: int) -> None:
        self.raw[5] = value & 0xFF


@dataclass
class SliderSlot:
    """5-byte fader record: ``type, channel, data1, min, max``."""

    raw: memoryview

    @classmethod
    def empty(cls) -> SliderSlot:
        return cls(memoryview(bytearray(SLIDER_SIZE)))

    @property
    def type(self) -> int:
        return self.raw[0]

    @type.setter
    def type(self, value: int) -> None:
        self.raw[0] = value & 0xFF

    @property
    def channel(self) -> int:
        return self.raw[1]

    @channel.setter
    def channel(self, value: int) -> None:
        self.raw[1] = value & 0xFF

    @property
    def data1(self) -> int:
        return self.raw[2]

    @data1.setter
    def data1(self, value: int) -> None:
        self.raw[2] = value & 0xFF

    @property
    def minimum(self) -> int:
        return self.raw[3]

    @minimum.setter
    def minimum(self, value: int) -> None:
        self.raw[3] = value & 0xFF

    @property
    def maximum(self) -> int:
        return self.raw[4]

    @maximum.setter
    def maximum(self, value: int) -> None:
        self.raw[4] = value & 0xFF


class Preset:
    """One 3141-byte preset.

    With ``copy=False`` the preset edits the buffer in place (used by the GUI
    so that changes go straight into the device image).
    """

    def __init__(self, data, copy: bool = True):
        if len(data) != PRESET_SIZE:
            raise ValueError(f"preset must be {PRESET_SIZE} bytes")
        if copy:
            self.data = bytearray(data)
        else:
            self.data = data if isinstance(data, memoryview) else memoryview(data)

    # -- controls ----------------------------------------------------------
    def button(self, index: int) -> ButtonSlot:
        if not 0 <= index < BUTTON_COUNT:
            raise IndexError(index)
        start = BUTTON_OFFSET + index * BUTTON_SIZE
        return ButtonSlot(memoryview(self.data)[start : start + BUTTON_SIZE])

    def knob(self, index: int) -> KnobSlot:
        if not 0 <= index < KNOB_COUNT:
            raise IndexError(index)
        start = KNOB_OFFSET + index * KNOB_SIZE
        return KnobSlot(memoryview(self.data)[start : start + KNOB_SIZE])

    def slider(self, index: int) -> SliderSlot:
        if not 0 <= index < SLIDER_COUNT:
            raise IndexError(index)
        start = SLIDER_OFFSET + index * SLIDER_SIZE
        return SliderSlot(memoryview(self.data)[start : start + SLIDER_SIZE])

    # -- serialisation -----------------------------------------------------
    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def to_dict(self) -> dict:
        return {
            "buttons": [
                {
                    "type": b.type,
                    "channel": b.channel,
                    "data1": b.data1,
                    "value_off": b.value_off,
                    "value_on": b.value_on,
                    "led": b.led,
                    "sysex": b.sysex.hex(),
                }
                for b in (self.button(i) for i in range(BUTTON_COUNT))
            ],
            "knobs": [
                {
                    "type": k.type,
                    "channel": k.channel,
                    "curve": k.curve,
                    "data1": k.data1,
                    "min": k.minimum,
                    "max": k.maximum,
                }
                for k in (self.knob(i) for i in range(KNOB_COUNT))
            ],
            "sliders": [
                {
                    "type": s.type,
                    "channel": s.channel,
                    "data1": s.data1,
                    "min": s.minimum,
                    "max": s.maximum,
                }
                for s in (self.slider(i) for i in range(SLIDER_COUNT))
            ],
        }

    @classmethod
    def from_dict(cls, value: dict) -> Preset:
        preset = cls(bytearray(PRESET_SIZE))
        for index, item in enumerate(value.get("buttons", [])):
            button = preset.button(index)
            for field in ("type", "channel", "data1", "value_off", "value_on", "led"):
                if field in item:
                    setattr(button, field, int(item[field]))
            for old, new in (("data2", "value_off"), ("option", "value_on"),
                             ("flag", "led")):
                if old in item and new not in item:
                    setattr(button, new, int(item[old]))
            if "sysex" in item:
                button.sysex = bytes.fromhex(item["sysex"].replace(" ", ""))
        for index, item in enumerate(value.get("knobs", [])):
            knob = preset.knob(index)
            for field, attr in (
                ("type", "type"),
                ("channel", "channel"),
                ("curve", "curve"),
                ("data1", "data1"),
                ("min", "minimum"),
                ("max", "maximum"),
            ):
                if field in item:
                    setattr(knob, attr, int(item[field]))
        for index, item in enumerate(value.get("sliders", [])):
            slider = preset.slider(index)
            for field, attr in (
                ("type", "type"),
                ("channel", "channel"),
                ("data1", "data1"),
                ("min", "minimum"),
                ("max", "maximum"),
            ):
                if field in item:
                    setattr(slider, attr, int(item[field]))
        return preset


class SmcMixer:
    """Complete device state (globals + both presets)."""

    def __init__(self, globals_: bytes, user: bytes):
        if len(globals_) < GLOBAL_SIZE:
            globals_ = globals_.ljust(GLOBAL_SIZE, b"\x00")
        if len(user) != USER_SIZE:
            raise ValueError(f"user block must be {USER_SIZE} bytes")
        self.globals = bytearray(globals_[:GLOBAL_SIZE])
        self.user = bytearray(user)

    @property
    def active_preset(self) -> int | None:
        """Index of the preset the device is currently running.

        The value lives in ``globals[0]`` (0-based) and is writable: writing it
        switches the device to that preset immediately.
        """
        value = int(self.globals[0])
        return value if 0 <= value < PRESET_COUNT else None

    def set_active_preset(self, index: int) -> None:
        if not 0 <= index < PRESET_COUNT:
            raise IndexError(index)
        self.globals[0] = index

    @classmethod
    def default(cls) -> SmcMixer:
        return cls(default_globals(), default_user_block())

    # Backwards compatible alias.
    factory = default

    # -- presets -----------------------------------------------------------
    def preset(self, index: int) -> Preset:
        if not 0 <= index < PRESET_COUNT:
            raise IndexError(index)
        start = index * PRESET_SIZE
        return Preset(self.user[start : start + PRESET_SIZE])

    def preset_view(self, index: int) -> Preset:
        """Return a preset that edits the device image in place."""
        if not 0 <= index < PRESET_COUNT:
            raise IndexError(index)
        start = index * PRESET_SIZE
        return Preset(memoryview(self.user)[start : start + PRESET_SIZE], copy=False)

    def set_preset(self, index: int, preset: Preset) -> None:
        start = index * PRESET_SIZE
        self.user[start : start + PRESET_SIZE] = preset.to_bytes()

    # -- import / export ---------------------------------------------------
    def to_json(self, device_name: str | None = None) -> str:
        document = {
            "format": "midisuite-linux/smc-mixer",
            "version": 1,
            "device": device_name,
            "globals": bytes(self.globals).hex(),
            "user": bytes(self.user).hex(),
            "presets": [self.preset(i).to_dict() for i in range(PRESET_COUNT)],
        }
        return json.dumps(document, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> SmcMixer:
        document = json.loads(text)
        if "user" in document:
            mixer = cls(bytes.fromhex(document.get("globals", "")), bytes.fromhex(document["user"]))
        else:
            mixer = cls(b"", default_user_block())
        for index, preset_data in enumerate(document.get("presets", [])):
            mixer.set_preset(index, Preset.from_dict(preset_data))
        return mixer
