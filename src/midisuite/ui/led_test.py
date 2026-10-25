"""Dialog for testing the SMC-Mixer's MIDI LED feedback."""

from __future__ import annotations

import rtmidi
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..devices.smc_mixer import BUTTON_COUNT, SLIDER_COUNT
from ..led import button_led_note, note_off, note_on, pitch_bend_7bit
from .panel import button_caption


def _output_ports() -> list[str]:
    try:
        out = rtmidi.MidiOut()
        ports = list(out.get_ports())
        del out
        return ports
    except Exception:
        return []


def _input_ports() -> list[str]:
    try:
        source = rtmidi.MidiIn()
        ports = list(source.get_ports())
        del source
        return ports
    except Exception:
        return []


def _default_port(ports: list[str]) -> int:
    if not ports:
        return -1
    for i, name in enumerate(ports):
        if "SMC-Mixer-Master" in name:
            return i
    for i, name in enumerate(ports):
        if "SMC-Mixer" in name and "Private" not in name:
            return i
    for i, name in enumerate(ports):
        if "Bluetooth" in name or "BLE" in name:
            return i
    return 0


def _msb(value: int) -> int:
    """Convert a stored pitch-bend value to the 7-bit fader position."""
    return (value >> 7) & 0x7F if value > 0x7F else value


class LedTestDialog(QDialog):
    """Send the performance-MIDI messages that drive the device LEDs."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.preset = window.current_preset
        self.setWindowTitle("LED feedback test")
        self.resize(620, 560)
        self._out = None
        self._in = None
        self._last: dict[int, int] = {}
        self._fader_channel = 1
        self._learning = 0
        self._learn_token = 0
        self._loading = False

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll_input)

        self._build()
        self.mode_label.setText(self._mode_text())
        self._refresh_ports()
        self._button_changed()
        self._fader_changed()
        self.finished.connect(self._cleanup)

    # -- UI ----------------------------------------------------------------
    def _mode_text(self) -> str:
        active = self.window.active_preset
        if self.preset is None:
            return "Read the configuration from the device first."
        if active is None:
            text = (
                "Active preset unknown. Press “Read from device” so the "
                "editor can tell whether the DAW slot is selected."
            )
        elif active == 0:
            text = (
                "DAW slot (Preset 1) is active: the fader soft-takeover "
                "indicators are available."
            )
        else:
            text = (
                f"Preset {active + 1} (CC mode) is active: the fader "
                "soft-takeover indicators only respond in the DAW slot "
                "(Preset 1). Button LEDs with a note LED field work in "
                "both presets."
            )
        if getattr(self.window, "dirty", False):
            text += (
                "  The editor has unsaved changes; the device is still using "
                "its saved preset."
            )
        return text

    def _build(self) -> None:
        self._loading = True
        title = QLabel("Test the device's LED feedback")
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        title.setFont(font)

        self.mode_label = QLabel()
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet("color: #7d858f;")

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(320)
        self.port_combo.currentIndexChanged.connect(lambda _: self._open_ports())
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_ports)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("MIDI output:"))
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(refresh)

        # Button LEDs ------------------------------------------------------
        buttons = QGroupBox("Button LEDs")
        self.button_combo = QComboBox()
        for index in range(BUTTON_COUNT):
            self.button_combo.addItem(button_caption(index), index)
        self.button_combo.currentIndexChanged.connect(lambda _: self._button_changed())
        if self.window.selection and self.window.selection[0] == "button":
            self.button_combo.setCurrentIndex(self.window.selection[1])

        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 16)
        self.note_spin = QSpinBox()
        self.note_spin.setRange(0, 127)
        self.note_spin.setToolTip(
            "Incoming Note On/Off with this number controls the LED."
        )

        form = QFormLayout()
        form.addRow("Button:", self.button_combo)
        form.addRow("Channel:", self.channel_spin)
        form.addRow("Note:", self.note_spin)

        note_on_button = QPushButton("Note On")
        note_on_button.clicked.connect(self._send_note_on)
        note_off_button = QPushButton("Note Off")
        note_off_button.clicked.connect(self._send_note_off)
        use_led = QPushButton("Use LED field")
        use_led.setToolTip("Copy the button's LED note into the Note field")
        use_led.clicked.connect(self._use_led_field)
        button_actions = QHBoxLayout()
        button_actions.addWidget(note_on_button)
        button_actions.addWidget(note_off_button)
        button_actions.addWidget(use_led)
        button_actions.addStretch(1)

        self.led_label = QLabel()
        self.led_label.setWordWrap(True)
        self.led_label.setStyleSheet("color: #7d858f;")

        button_layout = QVBoxLayout(buttons)
        button_layout.addLayout(form)
        button_layout.addLayout(button_actions)
        button_layout.addWidget(self.led_label)

        # Fader indicators --------------------------------------------------
        faders = QGroupBox("Fader indicators (soft takeover)")
        self.fader_combo = QComboBox()
        for index in range(SLIDER_COUNT):
            self.fader_combo.addItem(f"Strip {index + 1} · fader", index)
        self.fader_combo.currentIndexChanged.connect(lambda _: self._fader_changed())
        if self.window.selection and self.window.selection[0] == "slider":
            self.fader_combo.setCurrentIndex(self.window.selection[1])

        self.value_spin = QSpinBox()
        self.value_spin.setRange(0, 127)
        self.value_spin.setValue(64)
        self.value_spin.setToolTip(
            "Pitch Bend value in the 7-bit form the SMC-Mixer faders use."
        )

        fader_form = QFormLayout()
        fader_form.addRow("Fader:", self.fader_combo)
        fader_form.addRow("Value:", self.value_spin)

        learn = QPushButton("Learn from device")
        learn.setToolTip("Listen for 5 seconds and take the physical fader position")
        learn.clicked.connect(self._start_learn)
        send = QPushButton("Send value")
        send.clicked.connect(self._send_fader_value)
        blink = QPushButton("Blink (mismatch)")
        blink.setToolTip("Send a value that differs from the learned position")
        blink.clicked.connect(self._send_blink)
        match = QPushButton("Match (off)")
        match.setToolTip("Send the learned fader position, which turns the LED off")
        match.clicked.connect(self._send_match)
        fader_actions = QHBoxLayout()
        for widget in (learn, send, blink, match):
            fader_actions.addWidget(widget)
        fader_actions.addStretch(1)

        self.learn_label = QLabel("Last fader value: —")
        self.learn_label.setWordWrap(True)
        self.fader_hint = QLabel(
            "The LED under the knob is the fader's soft-takeover indicator: "
            "a mismatching Pitch Bend makes it blink, a matching value turns "
            "it off. It only works while the DAW slot (Preset 1) is active."
        )
        self.fader_hint.setWordWrap(True)
        self.fader_hint.setStyleSheet("color: #7d858f;")

        fader_layout = QVBoxLayout(faders)
        fader_layout.addLayout(fader_form)
        fader_layout.addLayout(fader_actions)
        fader_layout.addWidget(self.learn_label)
        fader_layout.addWidget(self.fader_hint)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #7d858f;")

        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.mode_label)
        layout.addLayout(port_row)
        layout.addWidget(buttons)
        layout.addWidget(faders)
        layout.addWidget(self.status)
        layout.addLayout(close_row)
        self._loading = False

    # -- ports -------------------------------------------------------------
    def _refresh_ports(self) -> None:
        ports = _output_ports()
        current = self.port_combo.currentText()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        index = ports.index(current) if current in ports else _default_port(ports)
        self.port_combo.setCurrentIndex(index)
        self.port_combo.blockSignals(False)
        self._open_ports()

    def _open_ports(self) -> None:
        self._close_ports()
        if self.port_combo.currentIndex() < 0:
            self._status("No MIDI output ports found.")
            return
        try:
            out = rtmidi.MidiOut()
            out.open_port(self.port_combo.currentIndex())
            self._out = out
        except Exception as exc:
            self._status(f"Cannot open the MIDI output: {exc}")
            return

        name = self.port_combo.currentText()
        inputs = _input_ports()
        match = next((i for i, candidate in enumerate(inputs) if candidate == name), None)
        if match is None:
            self.learn_label.setText(
                "Last fader value: — (no matching MIDI input, learning unavailable)"
            )
            self._status(
                f"Sending to {name}.  No matching MIDI input for learning; "
                "set the value manually."
            )
            return
        try:
            source = rtmidi.MidiIn()
            source.open_port(match)
            source.ignore_types(sysex=True, timing=True, active_sense=True)
            self._in = source
            self._timer.start()
        except Exception as exc:
            self.learn_label.setText(
                f"Last fader value: — (input unavailable: {exc})"
            )
            return
        self._status(f"Sending to {name}; listening to the same port.")

    def _close_ports(self) -> None:
        self._timer.stop()
        for port in (self._in, self._out):
            if port is not None:
                try:
                    port.close_port()
                except Exception:
                    pass
        self._in = None
        self._out = None

    def _cleanup(self, *_args) -> None:
        self._learning = 0
        self._learn_token += 1
        self._close_ports()

    # -- status ------------------------------------------------------------
    def _status(self, text: str) -> None:
        self.status.setText(text)

    def _send(self, data: bytes, description: str) -> bool:
        if self._out is None:
            self._status("No MIDI output is open.")
            return False
        try:
            self._out.send_message(list(data))
        except Exception as exc:
            self._status(f"Send failed: {exc}")
            return False
        self._status(f"Sent {description}: {data.hex(' ')}")
        return True

    # -- buttons -----------------------------------------------------------
    def _selected_button(self):
        if self.preset is None:
            return None
        return self.preset.button(self.button_combo.currentData())

    def _button_changed(self) -> None:
        if self._loading:
            return
        slot = self._selected_button()
        if slot is None:
            return
        self._loading = True
        self.channel_spin.setValue(slot.channel + 1)
        note = button_led_note(slot)
        if note is not None:
            self.note_spin.setValue(note)
            self.led_label.setText(
                f"LED field 0x{slot.led:02X}: the LED follows note {note} "
                f"on channel {slot.channel + 1}."
            )
        else:
            default = slot.data1 if slot.type == 5 else 16
            self.note_spin.setValue(default)
            if slot.led == 0xFF:
                self.led_label.setText(
                    "LED field 0xFF: the LED follows the button itself, so "
                    "incoming note feedback is ignored. Set the LED field to "
                    "a note number in the inspector to control it from MIDI."
                )
            else:
                self.led_label.setText(
                    f"LED field 0x{slot.led:02X} has no verified note feedback; "
                    "try a note or set a note number in the inspector."
                )
        self._loading = False

    def _use_led_field(self) -> None:
        slot = self._selected_button()
        if slot is None:
            return
        note = button_led_note(slot)
        if note is None:
            self._status(
                "The LED field is 0xFF: the LED follows the button. Set a "
                "note number in the inspector to control it externally."
            )
            return
        self.note_spin.setValue(note)
        self.channel_spin.setValue(slot.channel + 1)
        self._status(f"Note field set from the LED byte: {note}.")

    def _send_note_on(self) -> None:
        self._send(
            note_on(self.channel_spin.value(), self.note_spin.value()),
            f"Note On {self.note_spin.value()} on channel {self.channel_spin.value()}",
        )

    def _send_note_off(self) -> None:
        self._send(
            note_off(self.channel_spin.value(), self.note_spin.value()),
            f"Note Off {self.note_spin.value()} on channel {self.channel_spin.value()}",
        )

    # -- faders ------------------------------------------------------------
    def _selected_fader(self):
        if self.preset is None:
            return None
        return self.preset.slider(self.fader_combo.currentData())

    def _fader_changed(self) -> None:
        if self._loading:
            return
        slot = self._selected_fader()
        if slot is None:
            return
        self._fader_channel = slot.channel + 1
        self.learn_label.setText("Last fader value: —")
        if slot.type != 2:
            self.fader_hint.setText(
                f"Fader {self.fader_combo.currentData() + 1} is not in Pitch "
                "Bend mode, so the device may not update its indicator. Set "
                "the fader mode to “Pitch bend” in the inspector."
            )
        else:
            self.fader_hint.setText(
                "The LED under the knob is the fader's soft-takeover indicator: "
                "a mismatching Pitch Bend makes it blink, a matching value "
                "turns it off. It only works while the DAW slot (Preset 1) is "
                "active."
            )

    def _poll_input(self) -> None:
        if self._in is None:
            return
        while True:
            message = self._in.get_message()
            if message is None:
                break
            data = message[0]
            if len(data) < 3 or (data[0] & 0xF0) != 0xE0:
                continue
            channel = (data[0] & 0x0F) + 1
            value = (data[2] << 7) | data[1]
            self._last[channel] = value
            if channel != self._fader_channel:
                continue
            self.learn_label.setText(
                f"Last fader value: {_msb(value)} (raw 14-bit {value})"
            )
            if self._learning:
                self.value_spin.setValue(_msb(value))
                self._learning = 0
                self._status(
                    f"Learned fader {self.fader_combo.currentData() + 1} = "
                    f"{_msb(value)}."
                )

    def _start_learn(self) -> None:
        if self._in is None:
            self._status("No matching MIDI input is open for learning.")
            return
        channel = self._fader_channel
        self._last.pop(channel, None)
        self._learning = 1
        self._learn_token += 1
        token = self._learn_token
        self._status(
            f"Listening for fader {self.fader_combo.currentData() + 1} "
            "(move it now, 5 seconds)…"
        )
        QTimer.singleShot(5000, lambda: self._learn_timeout(token))

    def _learn_timeout(self, token: int) -> None:
        if token != self._learn_token or not self._learning:
            return
        self._learning = 0
        self._status("No Pitch Bend received; move the fader while listening.")

    def _known_position(self) -> int | None:
        value = self._last.get(self._fader_channel)
        return None if value is None else _msb(value)

    def _send_fader_value(self) -> None:
        value = self.value_spin.value()
        self._send(
            pitch_bend_7bit(self._fader_channel, value),
            f"Pitch Bend {value} on channel {self._fader_channel}",
        )

    def _send_blink(self) -> None:
        known = self._known_position()
        base = self.value_spin.value() if known is None else known
        value = (base + 64) % 128
        self._send(
            pitch_bend_7bit(self._fader_channel, value),
            f"mismatching Pitch Bend {value} on channel {self._fader_channel}",
        )

    def _send_match(self) -> None:
        known = self._known_position()
        value = self.value_spin.value() if known is None else known
        self._send(
            pitch_bend_7bit(self._fader_channel, value),
            f"matching Pitch Bend {value} on channel {self._fader_channel}",
        )
