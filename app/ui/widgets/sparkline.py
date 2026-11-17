"""Data visualization widgets: sparkline, gauge bar and arc gauge.

Used by the system monitor page and the status bar. All painting is
theme-aware and updates automatically when the theme changes.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, Optional

from PyQt5.QtCore import QPointF, QRectF, QVariantAnimation, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from app.ui.theme import Theme


class Sparkline(QWidget):
    """Smoothed line chart with gradient fill for a 0..100 value series."""

    def __init__(self, color: str = "", height: int = 64, parent=None,
                 auto_scale: bool = False) -> None:
        super().__init__(parent)
        self._color_name = color
        self._data: Deque[float] = deque(maxlen=160)
        self._auto_scale = auto_scale
        self.setFixedHeight(height)
        self.setMinimumWidth(80)
        Theme.instance().changed.connect(lambda: self.update())

    def set_data(self, values: Iterable[float]) -> None:
        self._data = deque(values, maxlen=160)
        self.update()

    def push(self, value: float) -> None:
        self._data.append(float(value))
        self.update()

    def _color(self) -> QColor:
        theme = Theme.instance()
        return QColor(self._color_name or theme.token("accent"))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self._color()
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if not self._data:
            painter.setPen(QPen(QColor(Theme.instance().token("border_strong")), 1))
            painter.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())
            painter.end()
            return

        series = list(self._data)
        if self._auto_scale:
            peak = max(series) or 1.0
            low = min(series) or 0.0
        else:
            peak, low = 100.0, 0.0
        span = max(1.0, peak - low)

        def point_at(index: int) -> QPointF:
            x = rect.left() + (rect.width() * index / max(1, len(series) - 1))
            normalized = (series[index] - low) / span
            y = rect.bottom() - normalized * rect.height() * 0.92 - rect.height() * 0.04
            return QPointF(x, y)

        path = QPainterPath(point_at(0))
        for index in range(1, len(series)):
            previous = point_at(index - 1)
            current = point_at(index)
            mid_x = (previous.x() + current.x()) / 2
            path.cubicTo(QPointF(mid_x, previous.y()), QPointF(mid_x, current.y()), current)

        # Gradient fill under the line.
        fill_path = QPainterPath(path)
        fill_path.lineTo(rect.right(), rect.bottom())
        fill_path.lineTo(rect.left(), rect.bottom())
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top = QColor(color)
        top.setAlpha(70)
        bottom = QColor(color)
        bottom.setAlpha(0)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fill_path)

        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Current value dot.
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(point_at(len(series) - 1), 3, 3)
        painter.end()


class GaugeBar(QWidget):
    """Horizontal percentage bar with a rounded fill."""

    def __init__(self, color: str = "", parent=None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._color_name = color
        self.setFixedHeight(7)
        Theme.instance().changed.connect(lambda: self.update())

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = Theme.instance().palette()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(palette.surface3))
        painter.drawRoundedRect(self.rect(), 3, 3)
        if self._value > 0:
            color = QColor(self._color_name or palette.accent)
            width = max(3, int(self.width() * self._value / 100.0))
            painter.setBrush(color)
            painter.drawRoundedRect(0, 0, width, self.height(), 3, 3)
        painter.end()


class ArcGauge(QWidget):
    """Circular progress arc with a centered label (CPU / RAM / Disk)."""

    def __init__(self, label: str = "", color: str = "", parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._value = 0.0
        self._display = 0.0
        self._color_name = color
        self._sub = ""
        self.setMinimumSize(132, 132)
        Theme.instance().changed.connect(lambda: self.update())
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(500)
        self._anim.valueChanged.connect(self._on_tick)

    def _on_tick(self, value) -> None:
        self._display = float(value)
        self.update()

    def set_value(self, value: float, sub: str = "") -> None:
        self._value = max(0.0, min(100.0, float(value)))
        if sub:
            self._sub = sub
        self._anim.stop()
        self._anim.setStartValue(self._display)
        self._anim.setEndValue(self._value)
        self._anim.start()

    def set_label(self, label: str) -> None:
        self._label = label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = Theme.instance()
        palette = theme.palette()
        color = QColor(self._color_name or palette.accent)

        side = min(self.width(), self.height())
        rect = QRectF(
            (self.width() - side) / 2 + 10, (self.height() - side) / 2 + 10,
            side - 20, side - 20,
        )

        # Track arc: 270 degrees starting bottom-left.
        start_angle = 225 * 16
        span_total = 270 * 16
        pen = QPen(QColor(palette.surface3), 9, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, start_angle, -span_total)

        span_value = int(span_total * self._display / 100.0)
        pen = QPen(color, 9, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, start_angle, -span_value)

        # Center text
        painter.setPen(QColor(palette.text))
        font = painter.font()
        font.setPointSizeF(max(9, side / 13))
        font.setBold(True)
        painter.setFont(font)
        text_rect = QRectF(0, 0, self.width(), self.height())
        painter.drawText(text_rect.translated(0, -6), Qt.AlignCenter, f"{self._display:.0f}%")
        font.setBold(False)
        font.setPointSizeF(max(7, side / 20))
        painter.setFont(font)
        painter.setPen(QColor(palette.text_muted))
        painter.drawText(text_rect.translated(0, 14), Qt.AlignCenter, self._label)
        if self._sub:
            painter.drawText(text_rect.translated(0, 30), Qt.AlignCenter, self._sub)
        painter.end()
