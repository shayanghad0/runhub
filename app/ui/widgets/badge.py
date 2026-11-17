"""Badges and status dots (shadcn/ui badge styling, Qt-native)."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, QVariantAnimation, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QLabel, QWidget

from app.ui.theme import Theme, rgba


class Badge(QLabel):
    """Pill-shaped status badge with a leading dot."""

    def __init__(self, text: str = "", color: str = "#8b93a7", parent=None,
                 subtle: bool = True) -> None:
        super().__init__(text, parent)
        self._color = color
        self._subtle = subtle
        self._theme = Theme.instance()
        self.setAlignment(Qt.AlignCenter)
        self._apply_style()

    def set_color(self, color: str) -> None:
        if color == self._color:
            return
        self._color = color
        self._apply_style()
        self.update()

    def restyle(self, text: str, color: str) -> "Badge":
        """Update text + color in one call (used for live status changes)."""
        self.setText(text)
        self.set_color(color)
        return self

    def _apply_style(self) -> None:
        if self._subtle:
            background = rgba(self._color, 0.14)
            foreground = self._color
        else:
            background = self._color
            foreground = "#ffffff" if self._color != "#ffffff" else "#000000"
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {foreground};"
            f" border-radius: 9px; padding: 2px 9px; font-size: 10px; font-weight: 600; }}"
        )

    @classmethod
    def for_status(cls, status_value: str, parent=None) -> "Badge":
        """Badge colored by a ProjectStatus value."""
        theme = Theme.instance()
        labels = {
            "stopped": "Stopped", "starting": "Starting…", "running": "Running",
            "stopping": "Stopping…", "crashed": "Crashed", "error": "Error",
        }
        return cls(labels.get(status_value, status_value),
                   theme.status_color(status_value), parent)


class StatusDot(QWidget):
    """Small circle with an optional pulse animation (running state)."""

    def __init__(self, color: str, diameter: int = 9, pulse: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._diameter = diameter
        self._pulse = pulse
        self._phase = 0.0
        self.setFixedSize(diameter + 10, diameter + 10)
        self._anim: Optional[QVariantAnimation] = None
        self._setup_anim()

    def _setup_anim(self) -> None:
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1400)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_phase)

    def _on_phase(self, value) -> None:
        self._phase = float(value)
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def set_pulsing(self, pulse: bool) -> None:
        """Enable/disable the pulse animation (running processes pulse)."""
        self._pulse = pulse
        if pulse:
            if self._anim.state() != QVariantAnimation.Running:
                self._anim.start()
        else:
            self._anim.stop()
            self._phase = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self._diameter / 2

        if self._pulse:
            halo = QColor(self._color)
            halo.setAlpha(int(90 * (1 - self._phase)))
            halo_radius = radius + 5 + self._phase * 4
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, halo_radius, halo_radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(center, radius, radius)
        painter.end()
