"""Property editor for the selected control."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..devices.smc_mixer import (
    BUTTON_TYPES,
    FADER_TYPES,
    KNOB_TYPES,
    Preset,
)
from .panel import button_caption

BUTTON_HINTS = {
    0: "Sends one CC with value 2 only.",
    1: "CC toggle: value 1 on odd presses, value 2 on even presses.",
    2: "CC momentary: value 1 while held, value 2 on release.",
    3: "Program change: CC0 = data 1, CC32 = value 2, then program = value 1.",
    4: "Sends the SysEx buffer as raw bytes (include F0/F7 yourself).",
    5: "Note: Note On = data 1 / value 1, Note Off = data 1 with velocity 0.",
    6: "Sends the SysEx buffer as raw bytes (include F0/F7 yourself).",
    7: "No message is sent.",
    8: "No message is sent.",
}
KNOB_HINTS = {
    0: "Absolute CC: value = round(position × max / 127).",
    1: "Channel pressure (absolute).",
    2: "Pitch bend (14-bit).",
    3: "Relative CC: the max value is sent for one direction, min for the other.",
}
FADER_HINTS = {
    0: "Absolute CC mapped to the min…max range.",
    1: "Channel pressure (aftertouch).",
    2: "Pitch bend (14-bit).",
    3: "No message is sent.",
    4: "No message is sent.",
}


def byte_spin(value: int, maximum: int = 255) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, maximum)
    spin.setValue(value)
    return spin


def type_combo(table: dict[int, str], value: int) -> QComboBox:
    combo = QComboBox()
    for key in sorted(table):
        combo.addItem(table[key], key)
    if value not in table:
        combo.addItem(f"Custom ({value})", value)
    index = combo.findData(value)
    combo.setCurrentIndex(max(index, 0))
    return combo


class Inspector(QWidget):
    changed = Signal()
    testRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preset: Preset | None = None
        self._key: tuple[str, int] | None = None
        self._loading = False

        self._title = QLabel("Select a control")
        font = self._title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self._title.setFont(font)
        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet("color: #7d858f;")
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #8f98a3;")

        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self._test = QPushButton("Test message")
        self._test.clicked.connect(self.testRequested)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addSpacing(6)
        layout.addWidget(self._form_host)
        layout.addWidget(self._hint)
        layout.addStretch(1)
        layout.addWidget(self._test)

    # -- context -----------------------------------------------------------
    def set_context(self, preset: Preset | None, key: tuple[str, int] | None) -> None:
        self._preset = preset
        self._key = key
        self._rebuild()

    def current_key(self) -> tuple[str, int] | None:
        return self._key

    # -- helpers -----------------------------------------------------------
    def _clear_form(self) -> None:
        while self._form.count():
            item = self._form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add(self, label: str, widget: QWidget) -> None:
        self._form.addRow(label, widget)

    def _commit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _rebuild(self) -> None:
        self._loading = True
        self._clear_form()
        preset, key = self._preset, self._key
        if preset is None or key is None:
            self._title.setText("Select a control")
            self._subtitle.setText("Click a knob, fader or button on the panel.")
            self._hint.setText("")
            self._test.setEnabled(False)
            self._loading = False
            return

        kind, index = key
        self._test.setEnabled(True)
        if kind == "button":
            self._build_button(preset.button(index), index)
        elif kind == "knob":
            self._build_knob(preset.knob(index), index)
        else:
            self._build_slider(preset.slider(index), index)
        self._loading = False

    # -- builders ----------------------------------------------------------
    def _build_button(self, slot, index: int) -> None:
        caption = button_caption(index)
        label, _, mark = caption.partition(" · ")
        self._title.setText(f"Button {index + 1} · {mark}")
        self._subtitle.setText(f"{label} · record {index * 71} (0x{index * 71:04x})")
        self._hint.setText(BUTTON_HINTS.get(slot.type, "Custom message mode."))

        mode = type_combo(BUTTON_TYPES, slot.type)
        mode.currentIndexChanged.connect(
            lambda _: self._set(slot, "type", mode.currentData())
        )
        self._add("Mode", mode)

        channel = byte_spin(slot.channel + 1, 16)
        channel.valueChanged.connect(
            lambda v: self._set(slot, "channel", v - 1)
        )
        self._add("Channel", channel)

        data1 = byte_spin(slot.data1, 127)
        data1.valueChanged.connect(lambda v: self._set(slot, "data1", v))
        self._add("Data 1", data1)

        value_off = byte_spin(slot.value_off, 127)
        value_off.valueChanged.connect(lambda v: self._set(slot, "value_off", v))
        self._add("Value 2 (off / bank LSB)", value_off)

        value_on = byte_spin(slot.value_on, 127)
        value_on.valueChanged.connect(lambda v: self._set(slot, "value_on", v))
        self._add("Value 1 (on / program)", value_on)

        led_mode = QComboBox()
        led_mode.setToolTip(
            "0xFF: the LED follows the button itself.  A MIDI note: incoming "
            "Note On/Off with that note controls the LED."
        )
        led_mode.addItem("Follow the button (0xFF)", 0xFF)
        led_mode.addItem("MIDI note…", "note")
        if 0x80 <= slot.led <= 0xFE:
            led_mode.addItem(f"Custom (0x{slot.led:02X})", slot.led)
        led_mode.setCurrentIndex(1 if slot.led <= 0x7F else 0)
        if 0x80 <= slot.led <= 0xFE:
            led_mode.setCurrentIndex(max(0, led_mode.findData(slot.led)))

        default_note = slot.led if slot.led <= 0x7F else (
            slot.data1 if slot.type == 5 else 16
        )
        led_note = byte_spin(default_note, 127)
        led_note.setToolTip(
            "Incoming Note On/Off with this number controls the LED "
            "(on the button's channel)."
        )
        led_note.setEnabled(slot.led <= 0x7F)

        def update_led_mode(_=None) -> None:
            data = led_mode.currentData()
            is_note = data == "note"
            led_note.setEnabled(is_note)
            if data == 0xFF:
                self._set(slot, "led", 0xFF)
            elif is_note:
                self._set(slot, "led", led_note.value())
            elif isinstance(data, int):
                self._set(slot, "led", data)

        led_mode.currentIndexChanged.connect(update_led_mode)
        led_note.valueChanged.connect(
            lambda value: self._set(slot, "led", value)
            if led_mode.currentData() == "note"
            else None
        )
        led_row = QHBoxLayout()
        led_row.setContentsMargins(0, 0, 0, 0)
        led_row.addWidget(led_mode, 1)
        led_row.addWidget(led_note)
        led_host = QWidget()
        led_host.setLayout(led_row)
        self._add("LED", led_host)

        sysex = QLineEdit(slot.sysex.hex(" "))
        sysex.setFont(QFont("Monospace"))
        sysex.setPlaceholderText("F0 … F7 (max 64 bytes)")
        sysex.editingFinished.connect(lambda: self._apply_sysex(slot, sysex))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._clear_sysex(slot, sysex))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(sysex, 1)
        row.addWidget(clear)
        host = QWidget()
        host.setLayout(row)
        self._add("SysEx", host)

    def _build_knob(self, slot, index: int) -> None:
        self._title.setText(f"Knob {index + 1}")
        self._subtitle.setText(f"Strip {index + 1} · record {3053 + index * 6}")
        self._hint.setText(KNOB_HINTS.get(slot.type, "Custom message mode."))

        mode = type_combo(KNOB_TYPES, slot.type)
        mode.currentIndexChanged.connect(
            lambda _: self._set(slot, "type", mode.currentData())
        )
        self._add("Mode", mode)

        channel = byte_spin(slot.channel + 1, 16)
        channel.valueChanged.connect(lambda v: self._set(slot, "channel", v - 1))
        self._add("Channel", channel)

        controller = byte_spin(slot.data1, 127)
        controller.valueChanged.connect(lambda v: self._set(slot, "data1", v))
        self._add("Controller", controller)

        curve = byte_spin(slot.curve)
        curve.valueChanged.connect(lambda v: self._set(slot, "curve", v))
        self._add("Curve / speed", curve)

        low = byte_spin(slot.minimum, 127)
        low.setToolTip("Relative mode: value sent in one direction")
        low.valueChanged.connect(lambda v: self._set(slot, "minimum", v))
        self._add("Min", low)

        high = byte_spin(slot.maximum, 127)
        high.setToolTip("Relative mode: value sent in the other direction; absolute: scales 0…max")
        high.valueChanged.connect(lambda v: self._set(slot, "maximum", v))
        self._add("Max / scale", high)

    def _build_slider(self, slot, index: int) -> None:
        self._title.setText(f"Fader {index + 1}")
        self._subtitle.setText(f"Strip {index + 1} · record {3101 + index * 5}")
        self._hint.setText(FADER_HINTS.get(slot.type, "Custom message mode."))

        mode = type_combo(FADER_TYPES, slot.type)
        mode.currentIndexChanged.connect(
            lambda _: self._set(slot, "type", mode.currentData())
        )
        self._add("Mode", mode)

        channel = byte_spin(slot.channel + 1, 16)
        channel.valueChanged.connect(lambda v: self._set(slot, "channel", v - 1))
        self._add("Channel", channel)

        controller = byte_spin(slot.data1, 127)
        controller.valueChanged.connect(lambda v: self._set(slot, "data1", v))
        self._add("Controller", controller)

        low = byte_spin(slot.minimum, 127)
        low.valueChanged.connect(lambda v: self._set(slot, "minimum", v))
        self._add("Min", low)

        high = byte_spin(slot.maximum, 127)
        high.valueChanged.connect(lambda v: self._set(slot, "maximum", v))
        self._add("Max", high)

    # -- mutations ---------------------------------------------------------
    def _set(self, slot, attribute: str, value) -> None:
        if self._loading or value is None:
            return
        if getattr(slot, attribute) == value:
            return
        setattr(slot, attribute, value)
        if attribute == "type":
            kind = self._key[0] if self._key else "button"
            hints = {
                "button": BUTTON_HINTS,
                "knob": KNOB_HINTS,
                "slider": FADER_HINTS,
            }[kind]
            self._hint.setText(hints.get(value, "Custom message mode."))
        self._commit()

    def _apply_sysex(self, slot, edit: QLineEdit) -> None:
        text = edit.text().replace(" ", "")
        if not text:
            slot.sysex = b""
            edit.setText("")
            self._commit()
            return
        try:
            data = bytes.fromhex(text)
        except ValueError:
            QMessageBox.warning(self, "SysEx", "Not a valid hexadecimal string")
            edit.setText(slot.sysex.hex(" "))
            return
        if len(data) > 64:
            QMessageBox.warning(self, "SysEx", "The device accepts up to 64 bytes")
            edit.setText(slot.sysex.hex(" "))
            return
        slot.sysex = data
        edit.setText(data.hex(" "))
        self._commit()

    def _clear_sysex(self, slot, edit: QLineEdit) -> None:
        slot.sysex = b""
        edit.setText("")
        self._commit()
