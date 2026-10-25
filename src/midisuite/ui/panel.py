"""Schematic SMC-Mixer panel (independent drawing, no vendor artwork)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from ..devices.smc_mixer import (
    BUTTON_COUNT,
    Preset,
)
from ..led import button_led_mode

STRIP_COUNT = 8
TRANSPORT_START = 32
TRANSPORT_COUNT = BUTTON_COUNT - TRANSPORT_START

BG = QColor("#15171a")
STRIP_BG = QColor("#1e2126")
CTRL_BG = QColor("#262b31")
CTRL_BORDER = QColor("#464d56")
TEXT = QColor("#aab2bd")
TEXT_DIM = QColor("#6d7681")
ACCENT = QColor("#3da5ff")
LED_ON = QColor("#55d66b")
LED_OFF = QColor("#3a3f45")

#: Printed mark and backlight colour of the four buttons in a strip.
STRIP_BUTTON_STYLES = [
    ("M", QColor("#ff9f1a")),
    ("S", QColor("#3da5ff")),
    ("R", QColor("#ff4d4d")),
    ("square", QColor("#e8eaed")),
]

#: Icons and backlight colours of the eleven transport buttons.
TRANSPORT_STYLES = [
    ("play", QColor("#55d66b")),
    ("pause", QColor("#ff4d4d")),
    ("record", QColor("#ff4d4d")),
    ("rewind", QColor("#e8eaed")),
    ("fastforward", QColor("#e8eaed")),
    ("previous", QColor("#e8eaed")),
    ("next", QColor("#e8eaed")),
    ("up", QColor("#e8eaed")),
    ("down", QColor("#e8eaed")),
    ("left", QColor("#e8eaed")),
    ("right", QColor("#e8eaed")),
]

STRIP_BUTTON_CAPTIONS = ["M", "S", "R", "■"]
TRANSPORT_CAPTIONS = [
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


def button_caption(index: int) -> str:
    """Return a readable caption for a button, using the printed marks."""
    if index < TRANSPORT_START:
        strip = index // 4 + 1
        return f"Strip {strip} · {STRIP_BUTTON_CAPTIONS[index % 4]}"
    return f"Transport · {TRANSPORT_CAPTIONS[index - TRANSPORT_START]}"


class DevicePanel(QWidget):
    """Clickable schematic of the mixer: 8 strips + 11 transport buttons."""

    controlSelected = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preset: Preset | None = None
        self._selected: tuple[str, int] | None = None
        self._rects: dict[tuple[str, int], QRectF] = {}
        self.setMinimumSize(720, 380)
        self.setMouseTracking(True)
        self.setToolTip("Click a control to edit it")

    # -- state -------------------------------------------------------------
    def set_preset(self, preset: Preset | None) -> None:
        self._preset = preset
        self.update()

    def set_selected(self, key: tuple[str, int] | None) -> None:
        self._selected = key
        self.update()

    def selected(self) -> tuple[str, int] | None:
        return self._selected

    # -- geometry ----------------------------------------------------------
    def _layout(self) -> None:
        self._rects.clear()
        margin = 14
        width = self.width()
        height = self.height()
        transport_h = 24
        transport_y = height - margin - transport_h
        area_top = 30
        area_bottom = transport_y - 14

        strip_w = (width - 2 * margin) / STRIP_COUNT
        knob_r = max(12.0, min(20.0, strip_w * 0.23))
        knob_cy = area_top + 24
        fader_top = knob_cy + knob_r + 34
        fader_h = max(60.0, area_bottom - fader_top - 34)
        fader_w = 12.0
        button = max(17.0, min(22.0, strip_w * 0.22))
        button_gap = 4.0

        for strip in range(STRIP_COUNT):
            x = margin + strip * strip_w
            cx = x + strip_w / 2
            self._rects[("knob", strip)] = QRectF(
                cx - knob_r, knob_cy - knob_r, knob_r * 2, knob_r * 2
            )
            fx = x + strip_w * 0.30
            self._rects[("slider", strip)] = QRectF(
                fx - fader_w / 2, fader_top, fader_w, fader_h
            )
            bx = x + strip_w * 0.56
            for row in range(4):
                index = strip * 4 + row
                if index >= TRANSPORT_START:
                    break
                self._rects[("button", index)] = QRectF(
                    bx,
                    fader_top + row * (button + button_gap),
                    button,
                    button,
                )

        total_w = width - 2 * margin
        gap = 6.0
        transport_w = (total_w - gap * (TRANSPORT_COUNT - 1)) / TRANSPORT_COUNT
        for i in range(TRANSPORT_COUNT):
            index = TRANSPORT_START + i
            self._rects[("button", index)] = QRectF(
                margin + i * (transport_w + gap),
                transport_y,
                transport_w,
                transport_h,
            )

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), BG)
        self._layout()

        margin = 14
        strip_w = (self.width() - 2 * margin) / STRIP_COUNT
        for strip in range(STRIP_COUNT):
            rect = QRectF(
                margin + strip * strip_w + 3,
                8,
                strip_w - 6,
                self.height() - 16,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(STRIP_BG)
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(TEXT_DIM)
            painter.setFont(QFont(self.font().family(), 8))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 2, rect.width(), 12),
                Qt.AlignmentFlag.AlignHCenter,
                str(strip + 1),
            )

        if self._preset is not None:
            for key, rect in self._rects.items():
                self._draw_control(painter, key, rect)

        painter.end()

    def _draw_control(self, painter: QPainter, key, rect: QRectF) -> None:
        kind, index = key
        selected = key == self._selected
        border = ACCENT if selected else CTRL_BORDER
        pen = QPen(border, 2 if selected else 1)
        painter.setPen(pen)
        painter.setBrush(CTRL_BG)

        if kind == "button":
            painter.drawRoundedRect(rect, 4, 4)
            slot = self._preset.button(index)
            if index < TRANSPORT_START:
                label, colour = STRIP_BUTTON_STYLES[index % 4]
            else:
                label, colour = TRANSPORT_STYLES[index - TRANSPORT_START]
            self._draw_glyph(painter, rect, label, colour)
        elif kind == "knob":
            painter.drawEllipse(rect)
            slot = self._preset.knob(index)
            painter.setPen(QPen(TEXT if not selected else ACCENT, 2))
            center = rect.center()
            angle = -135 + 270 * 0.7
            painter.drawLine(
                center,
                QPointF(
                    center.x() + rect.width() * 0.32 * math.cos(math.radians(angle)),
                    center.y() + rect.height() * 0.32 * math.sin(math.radians(angle)),
                ),
            )
            painter.setPen(TEXT_DIM)
            painter.setFont(QFont(self.font().family(), 7))
            painter.drawText(
                QRectF(rect.left() - 18, rect.bottom() + 3, rect.width() + 36, 12),
                Qt.AlignmentFlag.AlignHCenter,
                f"CC {slot.data1}",
            )
        else:  # slider
            painter.drawRoundedRect(rect, 5, 5)
            slot = self._preset.slider(index)
            handle = QRectF(
                rect.left() - 4,
                rect.top() + rect.height() * 0.45,
                rect.width() + 8,
                10,
            )
            painter.setBrush(QColor("#3b424b") if not selected else ACCENT)
            painter.setPen(QPen(border, 1))
            painter.drawRoundedRect(handle, 3, 3)
            painter.setPen(TEXT_DIM)
            painter.setFont(QFont(self.font().family(), 7))
            painter.drawText(
                QRectF(rect.left() - 18, rect.bottom() + 4, rect.width() + 36, 12),
                Qt.AlignmentFlag.AlignHCenter,
                f"CC {slot.data1}",
            )

    def _draw_glyph(
        self, painter: QPainter, rect: QRectF, kind: str, colour: QColor
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        centre = rect.center()
        cx, cy = centre.x(), centre.y()
        size = min(rect.width(), rect.height()) * 0.62
        half = size / 2

        if kind in ("M", "S", "R"):
            painter.setPen(QPen(colour, 1))
            font = QFont(self.font().family())
            font.setPixelSize(max(8, int(size * 1.15)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, kind)
        elif kind == "square":
            side = size * 0.62
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour, max(1.4, size * 0.14)))
            painter.drawRoundedRect(
                QRectF(cx - side / 2, cy - side / 2, side, side), 1.5, 1.5
            )
        elif kind == "play":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(cx - half * 0.55, cy - half * 0.9),
                        QPointF(cx - half * 0.55, cy + half * 0.9),
                        QPointF(cx + half * 0.9, cy),
                    ]
                )
            )
        elif kind == "pause":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            bar = size * 0.28
            painter.drawRoundedRect(
                QRectF(cx - half * 0.75, cy - half * 0.9, bar, size * 0.9), 1, 1
            )
            painter.drawRoundedRect(
                QRectF(cx + half * 0.75 - bar, cy - half * 0.9, bar, size * 0.9),
                1,
                1,
            )
        elif kind == "record":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawEllipse(centre, half * 0.75, half * 0.75)
        elif kind in ("rewind", "fastforward"):
            direction = -1 if kind == "rewind" else 1
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            for offset in (-0.45, 0.45):
                x = cx + offset * size
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(x - direction * half * 0.35, cy - half * 0.8),
                            QPointF(x - direction * half * 0.35, cy + half * 0.8),
                            QPointF(x + direction * half * 0.65, cy),
                        ]
                    )
                )
        elif kind in ("previous", "next"):
            direction = -1 if kind == "previous" else 1
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour, max(1.2, size * 0.16)))
            for offset in (-0.3, 0.3):
                x = cx + offset * size
                path = QPainterPath()
                path.moveTo(x - direction * size * 0.2, cy - half * 0.6)
                path.lineTo(x + direction * size * 0.22, cy)
                path.lineTo(x - direction * size * 0.2, cy + half * 0.6)
                painter.drawPath(path)
        elif kind in ("up", "down", "left", "right"):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour, max(1.2, size * 0.14)))
            points = {
                "up": [
                    QPointF(cx, cy - half * 0.8),
                    QPointF(cx - half * 0.8, cy + half * 0.55),
                    QPointF(cx + half * 0.8, cy + half * 0.55),
                ],
                "down": [
                    QPointF(cx, cy + half * 0.8),
                    QPointF(cx - half * 0.8, cy - half * 0.55),
                    QPointF(cx + half * 0.8, cy - half * 0.55),
                ],
                "left": [
                    QPointF(cx - half * 0.8, cy),
                    QPointF(cx + half * 0.55, cy - half * 0.8),
                    QPointF(cx + half * 0.55, cy + half * 0.8),
                ],
                "right": [
                    QPointF(cx + half * 0.8, cy),
                    QPointF(cx - half * 0.55, cy - half * 0.8),
                    QPointF(cx - half * 0.55, cy + half * 0.8),
                ],
            }[kind]
            painter.drawPolygon(QPolygonF(points))
        painter.restore()

    # -- interaction -------------------------------------------------------
    def _hit(self, pos: QPointF) -> tuple[str, int] | None:
        for key in reversed(list(self._rects)):
            if self._rects[key].adjusted(-2, -2, 2, 2).contains(pos):
                return key
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        key = self._hit(event.position())
        if key is not None:
            self._selected = key
            self.update()
            self.controlSelected.emit(*key)

    def mouseMoveEvent(self, event) -> None:
        key = self._hit(event.position())
        if key is None or self._preset is None:
            QToolTip.hideText()
            return
        kind, index = key
        if kind == "button":
            slot = self._preset.button(index)
            text = (
                f"{button_caption(index)}\n"
                f"mode {slot.type}, ch {slot.channel + 1}, data {slot.data1}\n"
                f"LED {button_led_mode(slot)}"
            )
        elif kind == "knob":
            slot = self._preset.knob(index)
            text = f"Strip {index + 1} · knob\nmode {slot.type}, ch {slot.channel + 1}, CC {slot.data1}"
        else:
            slot = self._preset.slider(index)
            text = (
                f"Strip {index + 1} · fader\n"
                f"mode {slot.type}, ch {slot.channel + 1}, CC {slot.data1}\n"
                "Soft-takeover indicator under the knob responds to Pitch Bend "
                "in the DAW slot (Preset 1)"
            )
        QToolTip.showText(event.globalPosition().toPoint(), text, self)
