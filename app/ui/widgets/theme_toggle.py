"""Animated dark/light mode toggle (pill with sliding knob).

Ports the ``theme-toggle`` component from the design system to Qt: a
56x28 pill, a circular knob that slides between the sun and moon, and a
smooth color transition.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QVariantAnimation, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from app.ui.icons import pixmap
from app.ui.theme import Theme


class ThemeToggle(QWidget):
    """Click to switch between dark and light mode."""

    toggled = pyqtSignal(bool)   # True = dark mode requested

    WIDTH, HEIGHT = 58, 28
    KNOB = 22

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle dark / light mode")
        self._dark = True
        self._position = 1.0   # 0 = light (knob left), 1 = dark (knob right)
        self._anim: Optional[QVariantAnimation] = None
        self._theme = Theme.instance()

    # ------------------------------------------------------------------ #

    def set_dark(self, dark: bool, animate: bool = True) -> None:
        self._dark = dark
        target = 1.0 if dark else 0.0
        if not animate:
            self._position = target
            self.update()
            return
        if self._anim is None:
            self._anim = QVariantAnimation(self)
            self._anim.setDuration(260)
            self._anim.setEasingCurve(  # type: ignore[assignment]
                __import__("PyQt5.QtCore", fromlist=["QEasingCurve"]).QEasingCurve.InOutCubic
            )
            self._anim.valueChanged.connect(self._on_tick)
        self._anim.stop()
        self._anim.setStartValue(self._position)
        self._anim.setEndValue(target)
        self._anim.start()

    def is_dark(self) -> bool:
        return self._dark

    def _on_tick(self, value) -> None:
        self._position = float(value)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        new_dark = not self._dark
        self.set_dark(new_dark)
        self.toggled.emit(new_dark)
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = self._theme
        palette = theme.palette()

        # Track
        track = QColor(palette.surface3) if self._dark else QColor(palette.surface2)
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self.HEIGHT // 2, self.HEIGHT // 2)

        # Side icons
        moon = pixmap("moon", palette.text_muted, 13)
        sun = pixmap("sun", palette.text_muted, 13)
        painter.drawPixmap(int(self.WIDTH - self.KNOB - 8), self.HEIGHT // 2 - 6, moon)
        painter.drawPixmap(int(8), self.HEIGHT // 2 - 6, sun)

        # Knob
        knob_x = 3 + (1 - self._position) * (self.WIDTH - self.KNOB - 6) + self._position * (self.WIDTH - self.KNOB - 6) * 0
        # Slide: left when light (position=0), right when dark (position=1)
        travel = self.WIDTH - self.KNOB - 6
        knob_x = 3 + self._position * travel
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(palette.accent))
        painter.drawRoundedRect(int(knob_x), 3, self.KNOB, self.KNOB, self.KNOB // 2, self.KNOB // 2)

        knob_icon = "moon" if self._position > 0.5 else "sun"
        icon_color = "#ffffff"
        knob_pix = pixmap(knob_icon, icon_color, 13)
        painter.drawPixmap(int(knob_x + (self.KNOB - 13) // 2), 3 + (self.KNOB - 13) // 2, knob_pix)
        painter.end()
