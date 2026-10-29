"""Midi Suite — SMC-Mixer editor for Linux (independent implementation)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import rtmidi
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..devices.smc_mixer import (
    BLOCK_GLOBAL,
    BLOCK_USER,
    GLOBAL_SIZE,
    PRESET_COUNT,
    PRESET_SIZE,
    USER_SIZE,
    SmcMixer,
    default_globals,
    default_preset,
)
from ..transport import (
    BaseTransport,
    TransportError,
    find_config_port,
    list_ble_devices,
    list_ports,
    open_transport,
)
from ..updates import (
    DEFAULT_INTERVAL,
    DEFAULT_REPO,
    INTERVAL_LABELS,
    Release,
    check_for_update,
    interval_seconds,
)
from .inspector import Inspector
from .led_test import LedTestDialog
from .panel import DevicePanel

APP_NAME = "Midi Suite"
ORG_NAME = "midisuite-linux"


class GlobalsTab(QWidget):
    """Hex editor for the 128-byte globals block."""

    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change
        self._loading = False
        self.text = QPlainTextEdit()
        self.text.setFont(QFont("Monospace"))
        self.text.textChanged.connect(self._changed)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Global block (block 4, 128 bytes).  Some bytes are live state and "
            "the meaning of most fields is not documented — edit with care."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self.text)

    def load(self, data: bytes) -> None:
        self._loading = True
        rows = []
        for offset in range(0, len(data), 16):
            chunk = data[offset : offset + 16]
            rows.append(f"{offset:04x}  {chunk.hex(' ')}")
        self.text.setPlainText("\n".join(rows))
        self._loading = False

    def value(self) -> bytes:
        data = bytearray()
        for line in self.text.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if len(line) > 4 and line[4] == " ":
                line = line[4:]
            data += bytes.fromhex(line.replace(" ", ""))
        if len(data) < GLOBAL_SIZE:
            data = data.ljust(GLOBAL_SIZE, b"\x00")
        return bytes(data[:GLOBAL_SIZE])

    def _changed(self) -> None:
        if not self._loading:
            self._on_change()


class MonitorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace"))
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Live traffic: → sent to the device, ← received from it.")
        )
        layout.addWidget(self.log)

    def append(self, direction: str, packet: bytes) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"{stamp} {direction} {packet.hex(' ')}")


class BleScanWorker(QThread):
    """Run a short BlueZ discovery without blocking the UI."""

    finished_scan = Signal(object)

    def __init__(self, seconds: float, parent=None):
        super().__init__(parent)
        self.seconds = seconds

    def run(self) -> None:
        self.finished_scan.emit(list_ble_devices(self.seconds))


class TestSender:
    """Virtual MIDI output used by the “Test message” button."""

    def __init__(self):
        self._out = None

    def send(self, messages: list[bytes]) -> None:
        if not messages:
            raise TransportError("this mode does not send any MIDI message")
        if self._out is None:
            out = rtmidi.MidiOut()
            out.open_virtual_port("MidiSuite Test")
            self._out = out
        for message in messages:
            self._out.send_message(list(message))


class UpdateCheckWorker(QThread):
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, repo: str, current: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.current = current

    def run(self) -> None:
        try:
            self.found.emit(check_for_update(self.repo, self.current))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Shows a newer release and a link to its page (nothing is installed)."""

    def __init__(self, parent, release: Release, current: str):
        super().__init__(parent)
        self._release = release
        self.setWindowTitle("Update available")
        self.resize(620, 440)

        title = QLabel(f"Midi Suite {release.version} is available")
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        title.setFont(font)
        subtitle = QLabel(
            f"You are running version {current}. "
            "Download the new version from the release page."
        )
        subtitle.setStyleSheet("color: #7d858f;")
        subtitle.setWordWrap(True)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.notes or "No release notes were provided.")

        page = QPushButton("Open release page")
        page.setEnabled(bool(release.page_url))
        page.clicked.connect(self._open_page)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(page)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Release notes:"))
        layout.addWidget(notes, 1)
        layout.addLayout(buttons)

    def _open_page(self) -> None:
        if self._release.page_url:
            QDesktopServices.openUrl(QUrl(self._release.page_url))


def build_test_messages(kind: str, slot) -> list[bytes]:
    channel = getattr(slot, "channel", 0) & 0x0F
    if kind == "button":
        mode = slot.type
        if mode == 0:
            return [bytes([0xB0 | channel, slot.data1, slot.value_off])]
        if mode in (1, 2):
            return [
                bytes([0xB0 | channel, slot.data1, slot.value_on]),
                bytes([0xB0 | channel, slot.data1, slot.value_off]),
            ]
        if mode == 3:
            return [
                bytes([0xB0 | channel, 0, slot.data1]),
                bytes([0xB0 | channel, 32, slot.value_off]),
                bytes([0xC0 | channel, slot.value_on]),
            ]
        if mode in (4, 6):
            return [slot.sysex] if slot.sysex else []
        if mode == 5:
            return [
                bytes([0x90 | channel, slot.data1, slot.value_on]),
                bytes([0x80 | channel, slot.data1, 0]),
            ]
        return []
    controller = getattr(slot, "data1", 0)
    if kind == "knob" and slot.type == 3:
        return [
            bytes([0xB0 | channel, controller, 0x7F]),
            bytes([0xB0 | channel, controller, 0x00]),
        ]
    mode = slot.type
    if mode == 0:
        return [bytes([0xB0 | channel, controller, 64])]
    if mode == 1:
        return [bytes([0xD0 | channel, 64])]
    if mode == 2:
        return [bytes([0xE0 | channel, 0, 64])]
    return []


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mixer: SmcMixer | None = None
        self.transport: BaseTransport | None = None
        self.preset_index = 0
        self.active_preset: int | None = None
        self.current_preset = None
        self.selection: tuple[str, int] | None = ("button", 0)
        self.dirty = False
        self.globals_dirty = False
        self.test_sender = TestSender()

        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._shadow: bytes | None = None
        self._last_key = None
        self._last_time = 0.0

        self.setWindowTitle("Midi Suite — SMC-Mixer")
        self.resize(1240, 760)
        self._build_actions()
        self._build_ui()
        self._restore_settings()
        self._update_actions()

        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(200)
        self._monitor_timer.timeout.connect(self._poll_traffic)
        self._monitor_timer.start()

        self._update_check_worker = None
        QTimer.singleShot(1500, self._auto_check_updates)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(10 * 60 * 1000)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start()

    # -- UI ----------------------------------------------------------------
    def _build_actions(self) -> None:
        self.act_import = QAction("&Import…", self, shortcut=QKeySequence(QKeySequence.StandardKey.Open))
        self.act_import.triggered.connect(self.import_file)
        self.act_export = QAction("&Export…", self, shortcut=QKeySequence(QKeySequence.StandardKey.SaveAs))
        self.act_export.triggered.connect(self.export_file)
        self.act_quit = QAction("&Quit", self, shortcut=QKeySequence(QKeySequence.StandardKey.Quit))
        self.act_quit.triggered.connect(self.close)

        self.act_connect = QAction("&Connect", self)
        self.act_connect.triggered.connect(self.toggle_connection)
        self.act_read = QAction("&Read from device", self, shortcut="F5")
        self.act_read.triggered.connect(self.read_device)
        self.act_save = QAction("&Save to device", self, shortcut=QKeySequence(QKeySequence.StandardKey.Save))
        self.act_save.triggered.connect(self.save_device)
        self.act_defaults = QAction("Reset preset to &defaults", self)
        self.act_defaults.triggered.connect(self.reset_defaults)
        self.act_copy = QAction("&Copy preset to the other slot", self)
        self.act_copy.triggered.connect(self.copy_preset)
        self.act_led_test = QAction("Test &LED feedback…", self)
        self.act_led_test.setToolTip(
            "Send the performance-MIDI messages that control the LEDs"
        )
        self.act_led_test.triggered.connect(self.show_led_test)

        self.act_undo = QAction("&Undo", self, shortcut=QKeySequence(QKeySequence.StandardKey.Undo))
        self.act_undo.triggered.connect(self.undo)
        self.act_redo = QAction("&Redo", self, shortcut=QKeySequence(QKeySequence.StandardKey.Redo))
        self.act_redo.triggered.connect(self.redo)

        self.act_check_updates = QAction("Check for &updates…", self)
        self.act_check_updates.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self.act_preferences = QAction("&Preferences…", self)
        self.act_preferences.triggered.connect(self.show_preferences)

        self.act_about = QAction("&About", self)
        self.act_about.triggered.connect(self.show_about)

        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        device_menu = menu.addMenu("&Device")
        device_menu.addAction(self.act_connect)
        device_menu.addAction(self.act_read)
        device_menu.addAction(self.act_save)
        device_menu.addSeparator()
        device_menu.addAction(self.act_defaults)
        device_menu.addAction(self.act_copy)
        device_menu.addSeparator()
        device_menu.addAction(self.act_led_test)
        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        help_menu = menu.addMenu("&Help")
        help_menu.addAction(self.act_check_updates)
        help_menu.addAction(self.act_preferences)
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel(" Port "))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        toolbar.addWidget(self.port_combo)
        self.act_refresh_ports = QAction("⟳", self)
        self.act_refresh_ports.setToolTip("Rescan MIDI ports")
        self.act_refresh_ports.triggered.connect(self.refresh_ports)
        toolbar.addAction(self.act_refresh_ports)
        self.act_scan_ble = QAction("Scan BLE", self)
        self.act_scan_ble.setToolTip("Scan for Bluetooth LE devices (6 seconds)")
        self.act_scan_ble.triggered.connect(self.start_ble_scan)
        toolbar.addAction(self.act_scan_ble)
        toolbar.addAction(self.act_connect)
        toolbar.addSeparator()
        toolbar.addAction(self.act_read)
        toolbar.addAction(self.act_save)
        toolbar.addSeparator()
        self.device_label = QLabel("not connected")
        toolbar.addWidget(self.device_label)
        self.refresh_ports()

    def _build_ui(self) -> None:
        self.panel = DevicePanel()
        self.panel.controlSelected.connect(self.select_control)
        self.inspector = Inspector()
        self.inspector.changed.connect(self.control_changed)
        self.inspector.testRequested.connect(self.send_test_message)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.panel)
        splitter.addWidget(self.inspector)
        self.inspector.setMinimumWidth(340)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([800, 400])

        device_tab = QWidget()
        layout = QVBoxLayout(device_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.globals_tab = GlobalsTab(self.globals_changed)
        self.monitor_tab = MonitorTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(device_tab, "Device")
        self.tabs.addTab(self.globals_tab, "Globals")
        self.tabs.addTab(self.monitor_tab, "Monitor")

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([f"Preset {i + 1}" for i in range(PRESET_COUNT)])
        self.preset_combo.currentIndexChanged.connect(self.switch_preset)
        preset_row.addWidget(self.preset_combo)
        self.btn_activate = QPushButton("Activate on device")
        self.btn_activate.setToolTip(
            "Switch the device to the selected preset (writes the active preset byte)"
        )
        self.btn_activate.clicked.connect(self.activate_preset)
        preset_row.addWidget(self.btn_activate)

        self.btn_copy = QPushButton("Copy to other slot")
        self.btn_copy.clicked.connect(self.copy_preset)
        self.btn_defaults = QPushButton("Reset to defaults")
        self.btn_defaults.clicked.connect(self.reset_defaults)
        self.btn_import = QPushButton("Import…")
        self.btn_import.clicked.connect(self.import_file)
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self.export_file)
        for button in (self.btn_copy, self.btn_defaults, self.btn_import, self.btn_export):
            preset_row.addWidget(button)
        preset_row.addStretch(1)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addLayout(preset_row)
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Connect the SMC-Mixer over USB and press Read.")

    # -- settings ----------------------------------------------------------
    def _settings(self) -> QSettings:
        return QSettings(ORG_NAME, "smc-mixer")

    def _restore_settings(self) -> None:
        settings = self._settings()
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        port_key = settings.value("port_key")
        if port_key:
            index = self.port_combo.findData(str(port_key))
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def _save_settings(self) -> None:
        settings = self._settings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("port_key", self.port_combo.currentData())

    # -- connection --------------------------------------------------------
    def refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for port in list_ports():
            self.port_combo.addItem(f"USB  {port}", f"usb:{port}")
        for device in list_ble_devices():
            self.port_combo.addItem(f"BLE  {device.label}", f"ble:{device.address}")

        preferred = [current, self._settings().value("port_key")]
        default = find_config_port()
        if default:
            preferred.append(f"usb:{default}")
        for key in preferred:
            if not key:
                continue
            index = self.port_combo.findData(key)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
                return
        if self.port_combo.count():
            self.port_combo.setCurrentIndex(0)

    def start_ble_scan(self) -> None:
        if getattr(self, "_scan_worker", None) is not None:
            return
        self.act_scan_ble.setEnabled(False)
        self.statusBar().showMessage("scanning for Bluetooth LE devices…")
        worker = BleScanWorker(6.0, self)
        worker.finished_scan.connect(self._on_ble_scan)
        worker.finished.connect(worker.deleteLater)
        self._scan_worker = worker
        worker.start()

    def _on_ble_scan(self, devices) -> None:
        self._scan_worker = None
        self.act_scan_ble.setEnabled(True)
        self.refresh_ports()
        self.statusBar().showMessage(
            f"BLE scan finished: {len(devices)} device(s) found", 5000
        )

    def toggle_connection(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None
            self.act_connect.setText("&Connect")
            self.device_label.setText("not connected")
            self._update_actions()
            return
        data = self.port_combo.currentData()
        if not data:
            QMessageBox.warning(self, "Connection", "No MIDI port or BLE device selected")
            return
        kind, value = str(data).split(":", 1)
        try:
            if kind == "ble":
                self.statusBar().showMessage(f"connecting to {value} via BLE…")
                QApplication.processEvents()
                transport = open_transport(ble_address=value)
            else:
                transport = open_transport(port=value)
            name = transport.name_and_version()
        except (TransportError, ValueError, OSError, rtmidi.SystemError) as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            self.statusBar().showMessage("connection failed", 4000)
            return
        self.transport = transport
        self.act_connect.setText("&Disconnect")
        source = value if kind == "usb" else f"BLE {value}"
        self.device_label.setText(f"{name}  ·  {source}")
        self.statusBar().showMessage(f"connected to {name}", 4000)
        self._update_actions()

    # -- data --------------------------------------------------------------
    def _require_mixer(self) -> SmcMixer | None:
        if self.mixer is None:
            QMessageBox.information(
                self, "No data", "Read the configuration from the device first."
            )
        return self.mixer

    def read_device(self) -> None:
        if self.transport is None:
            self.toggle_connection()
            if self.transport is None:
                return
        try:
            self.statusBar().showMessage("reading…")
            QApplication.processEvents()
            globals_ = self.transport.read_chunked(BLOCK_GLOBAL, 0, GLOBAL_SIZE)
            user = self.transport.read_chunked(BLOCK_USER, 0, USER_SIZE)
        except (TransportError, ValueError, OSError, rtmidi.SystemError) as exc:
            QMessageBox.critical(self, "Read failed", str(exc))
            self.statusBar().showMessage("read failed", 4000)
            return
        self.mixer = SmcMixer(globals_, user)
        self.active_preset = self._detect_active_preset()
        if self.active_preset is not None:
            self.preset_index = self.active_preset
            self.preset_combo.setCurrentIndex(self.active_preset)
        self.dirty = False
        self.globals_dirty = False
        self._reset_history()
        self.refresh_views()
        self.statusBar().showMessage("configuration read", 4000)

    def save_device(self) -> None:
        mixer = self._require_mixer()
        if mixer is None or self.transport is None:
            return
        try:
            self.statusBar().showMessage("writing…")
            QApplication.processEvents()
            self.transport.write_chunked(BLOCK_USER, 0, bytes(mixer.user))
            # Writes are live immediately but remain in RAM until the device
            # receives the zero-length "commit" write used by the vendor
            # editor's Save Config button.
            self.transport.commit(BLOCK_USER)
            if self.globals_dirty:
                self.transport.write_chunked(BLOCK_GLOBAL, 0, bytes(mixer.globals))
        except (TransportError, ValueError, OSError, rtmidi.SystemError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            self.statusBar().showMessage("save failed", 4000)
            return
        self.dirty = False
        self.globals_dirty = False
        self.statusBar().showMessage("saved and persisted to device", 4000)

    def _detect_active_preset(self) -> int | None:
        return self.mixer.active_preset if self.mixer is not None else None

    def activate_preset(self) -> None:
        mixer = self._require_mixer()
        if mixer is None:
            return
        if self.transport is None:
            QMessageBox.information(
                self, "Activate preset", "Connect to the device first."
            )
            return
        index = self.preset_index
        if self.active_preset == index:
            return
        answer = QMessageBox.question(
            self,
            "Activate preset",
            f"Switch the device to preset {index + 1}?\n\n"
            "The controls will start sending that preset's mappings.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.transport.write(BLOCK_GLOBAL, 0, bytes([index]))
        except (TransportError, ValueError, OSError, rtmidi.SystemError) as exc:
            QMessageBox.critical(self, "Activate preset failed", str(exc))
            return
        mixer.set_active_preset(index)
        self.active_preset = index
        self.refresh_views()
        self.statusBar().showMessage(f"device switched to preset {index + 1}", 4000)

    def switch_preset(self, index: int) -> None:
        self.preset_index = index
        self.refresh_views()

    def reset_defaults(self) -> None:
        mixer = self._require_mixer()
        if mixer is None:
            return
        start = self.preset_index * PRESET_SIZE
        mixer.user[start : start + PRESET_SIZE] = default_preset()
        self.note_edit(("preset", self.preset_index))
        self.refresh_views()
        self.statusBar().showMessage("preset reset to the built-in defaults")

    def copy_preset(self) -> None:
        mixer = self._require_mixer()
        if mixer is None:
            return
        source = self.preset_index
        target = 1 - source
        start_src = source * PRESET_SIZE
        start_dst = target * PRESET_SIZE
        mixer.user[start_dst : start_dst + PRESET_SIZE] = bytes(
            mixer.user[start_src : start_src + PRESET_SIZE]
        )
        self.note_edit(("preset", target))
        self.refresh_views()
        self.statusBar().showMessage(f"preset {source + 1} copied to preset {target + 1}")

    def refresh_views(self) -> None:
        if self.mixer is None:
            self.current_preset = None
            self.panel.set_preset(None)
            self.inspector.set_context(None, None)
            self._update_actions()
            return
        for i in range(PRESET_COUNT):
            label = f"Preset {i + 1}"
            if self.active_preset == i:
                label += "  ·  active on device"
            self.preset_combo.setItemText(i, label)
        self.current_preset = self.mixer.preset_view(self.preset_index)
        if self.selection is None:
            self.selection = ("button", 0)
        self.panel.set_preset(self.current_preset)
        self.panel.set_selected(self.selection)
        self.inspector.set_context(self.current_preset, self.selection)
        self.globals_tab.load(bytes(self.mixer.globals))
        self._update_actions()

    # -- editing -----------------------------------------------------------
    def select_control(self, kind: str, index: int) -> None:
        self.selection = (kind, index)
        self.inspector.set_context(self.current_preset, self.selection)

    def control_changed(self) -> None:
        self.panel.update()
        self.note_edit(self.inspector.current_key())

    def globals_changed(self) -> None:
        if self.mixer is None:
            return
        try:
            data = self.globals_tab.value()
        except ValueError:
            return
        if bytes(self.mixer.globals) != data:
            self.mixer.globals = bytearray(data)
            self.globals_dirty = True
            self.note_edit(("globals", 0))

    # -- undo --------------------------------------------------------------
    def _reset_history(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._shadow = bytes(self.mixer.user) if self.mixer else None
        self._last_key = None
        self._last_time = 0.0
        self._update_actions()

    def note_edit(self, key) -> None:
        if self.mixer is None:
            return
        now = time.monotonic()
        coalesce = (
            key == self._last_key
            and now - self._last_time < 1.5
            and bool(self._undo)
        )
        if not coalesce:
            if self._shadow is not None:
                self._undo.append(self._shadow)
                if len(self._undo) > 100:
                    del self._undo[0]
            self._redo.clear()
        self._shadow = bytes(self.mixer.user)
        self._last_key = key
        self._last_time = now
        self.dirty = True
        self._update_actions()

    def undo(self) -> None:
        if not self._undo or self.mixer is None:
            return
        current = bytes(self.mixer.user)
        previous = self._undo.pop()
        self._redo.append(current)
        self.mixer.user[:] = previous
        self._shadow = previous
        self.dirty = True
        self.refresh_views()
        self.statusBar().showMessage("undo", 2000)

    def redo(self) -> None:
        if not self._redo or self.mixer is None:
            return
        current = bytes(self.mixer.user)
        nxt = self._redo.pop()
        self._undo.append(current)
        self.mixer.user[:] = nxt
        self._shadow = nxt
        self.dirty = True
        self.refresh_views()
        self.statusBar().showMessage("redo", 2000)

    # -- files -------------------------------------------------------------
    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import configuration",
            "",
            "Midi Suite configuration (*.json *.bin);;All files (*)",
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            if path.lower().endswith(".json"):
                self.mixer = SmcMixer.from_json(raw.decode("utf-8"))
                self.globals_dirty = True
            else:
                if len(raw) != USER_SIZE:
                    raise ValueError(f"expected {USER_SIZE} bytes, got {len(raw)}")
                self.mixer = SmcMixer(default_globals(), raw)
        except (ValueError, KeyError, OSError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.dirty = True
        self._reset_history()
        self.refresh_views()
        self.statusBar().showMessage(f"imported {path}", 4000)

    def export_file(self) -> None:
        mixer = self._require_mixer()
        if mixer is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export configuration",
            "smc-mixer.json",
            "JSON (*.json);;Raw user block (*.bin)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".bin"):
                Path(path).write_bytes(bytes(mixer.user))
            else:
                Path(path).write_text(mixer.to_json(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"exported {path}", 4000)

    # -- test message ------------------------------------------------------
    def send_test_message(self) -> None:
        if self.current_preset is None or self.selection is None:
            return
        kind, index = self.selection
        if kind == "button":
            slot = self.current_preset.button(index)
        elif kind == "knob":
            slot = self.current_preset.knob(index)
        else:
            slot = self.current_preset.slider(index)
        messages = build_test_messages(kind, slot)
        try:
            self.test_sender.send(messages)
        except (TransportError, OSError, rtmidi.SystemError) as exc:
            QMessageBox.warning(self, "Test message", str(exc))
            return
        self.statusBar().showMessage(
            f"sent {len(messages)} message(s) to the virtual port “MidiSuite Test”",
            4000,
        )

    # -- misc --------------------------------------------------------------
    def _update_actions(self) -> None:
        has_data = self.mixer is not None
        for action in (
            self.act_save,
            self.act_export,
            self.act_defaults,
            self.act_copy,
            self.act_led_test,
        ):
            action.setEnabled(has_data)
        for button in (self.btn_defaults, self.btn_copy, self.btn_export):
            button.setEnabled(has_data)
        self.btn_activate.setEnabled(
            has_data and self.transport is not None and self.active_preset != self.preset_index
        )
        self.act_undo.setEnabled(bool(self._undo))
        self.act_redo.setEnabled(bool(self._redo))
        self.inspector.setEnabled(has_data)

    def _poll_traffic(self) -> None:
        if self.transport is None:
            return
        while True:
            packet = self.transport.pop_raw_packet()
            if packet is None:
                break
            self.monitor_tab.append("←", packet)
        while True:
            packet = self.transport.pop_sent_packet()
            if packet is None:
                break
            self.monitor_tab.append("→", packet)

    # -- updates -----------------------------------------------------------
    def _update_repo(self) -> str:
        return str(self._settings().value("update/repo", DEFAULT_REPO) or "").strip()

    def _update_interval(self) -> str:
        settings = self._settings()
        stored = settings.value("update/interval")
        if stored is None:
            # Migrate the previous boolean setting.
            legacy = settings.value("update/auto_check")
            if legacy is not None and str(legacy).lower() in ("0", "false", "no"):
                return "never"
            return DEFAULT_INTERVAL
        return str(stored)

    def _auto_check_updates(self) -> None:
        interval = interval_seconds(self._update_interval())
        if interval is None or not self._update_repo():
            return
        try:
            last = int(float(self._settings().value("update/last_check", 0) or 0))
        except (TypeError, ValueError):
            last = 0
        if time.time() - last < interval:
            return
        self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool = True) -> None:
        repo = self._update_repo()
        if not repo:
            if manual:
                QMessageBox.information(
                    self,
                    "Updates",
                    "The update repository is not configured.\n\n"
                    "Set it in Help → Preferences (format: owner/repository).",
                )
            return
        if self._update_check_worker is not None:
            return
        self._settings().setValue("update/last_check", int(time.time()))
        self.statusBar().showMessage("checking for updates…")
        worker = UpdateCheckWorker(repo, __version__, self)
        worker.found.connect(lambda update: self._on_update_checked(update, manual))
        worker.failed.connect(lambda message: self._on_update_failed(message, manual))
        worker.finished.connect(worker.deleteLater)
        self._update_check_worker = worker
        worker.start()

    def _on_update_checked(self, update, manual: bool) -> None:
        self._update_check_worker = None
        if update is None:
            if manual:
                QMessageBox.information(
                    self,
                    "Updates",
                    f"You are running the latest version ({__version__}).",
                )
            else:
                self.statusBar().showMessage("up to date", 4000)
            return
        self.statusBar().showMessage(
            f"update {update.version} available", 8000
        )
        dialog = UpdateDialog(self, update, __version__)
        dialog.exec()

    def _on_update_failed(self, message: str, manual: bool) -> None:
        self._update_check_worker = None
        if manual:
            QMessageBox.warning(self, "Update check failed", message)
        else:
            self.statusBar().showMessage(f"update check failed: {message}", 6000)

    def show_led_test(self) -> None:
        if self.mixer is None:
            QMessageBox.information(
                self, "LED feedback test", "Read the configuration from the device first."
            )
            return
        dialog = LedTestDialog(self)
        dialog.exec()

    def show_preferences(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Preferences")
        dialog.setMinimumWidth(460)
        repo = QLineEdit(self._update_repo())
        repo.setPlaceholderText("owner/repository")
        interval = QComboBox()
        for key, label in INTERVAL_LABELS:
            interval.addItem(label, key)
        current_interval = self._update_interval()
        index = interval.findData(current_interval)
        interval.setCurrentIndex(index if index >= 0 else interval.findData(DEFAULT_INTERVAL))

        form = QFormLayout()
        form.addRow("Update repository:", repo)
        form.addRow("Check for updates:", interval)

        save = QPushButton("Save")
        save.setDefault(True)
        cancel = QPushButton("Cancel")
        save.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)

        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        layout.addLayout(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._settings().setValue("update/repo", repo.text().strip())
            self._settings().setValue("update/interval", interval.currentData())
            self.statusBar().showMessage("preferences saved", 3000)
            self._auto_check_updates()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Midi Suite",
            "<b>Midi Suite — SMC-Mixer</b><br>"
            f"Version {__version__}<br><br>"
            "Independent Linux implementation of the M-VAVE / SINCO SMC-Mixer "
            "editor.<br><br>"
            "Protocol and memory layout were obtained by observing the device "
            "and are documented in <code>docs/protocol.md</code>. No vendor "
            "code or assets are used.",
        )

    def closeEvent(self, event) -> None:
        if self.dirty and self.mixer is not None:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                "The configuration has unsaved changes. Close anyway?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        if self.transport is not None:
            self.transport.close()
        self._save_settings()
        event.accept()


def main() -> int:
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"Midi Suite {__version__}")
        print(f"update repository: {DEFAULT_REPO or 'not configured'}")
        return 0
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
