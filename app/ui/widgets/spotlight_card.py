"""Spotlight card.

Implements the "spotlight glow" card from the design system: a rounded
card whose border and interior glow follow the mouse pointer with a
configurable hue (like the EaseMize/21st.dev spotlight component).
"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import QFrame, QGraphicsDropShadowEffect, QWidget

from app.ui.theme import Theme, rgba


class SpotlightCard(QFrame):
    """Rounded card with pointer-tracking glow. Custom-painted."""

    clicked = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        radius: int = 14,
        glow: bool = True,
        clickable: bool = True,
    ) -> None:
        super().__init__(parent)
        self._radius = radius
        self._glow_enabled = glow
        self._clickable = clickable
        self._mouse: QPointF = QPointF(-1000, -1000)
        self._hover = False
        self._glow_color: Optional[str] = None  # None = theme accent
        self._glow_strength = 1.0
        self._theme = Theme.instance()
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        if glow:
            self._install_shadow()

    def _install_shadow(self) -> None:
        """(Re)install the ambient drop shadow (removed by opacity fades)."""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #

    def set_glow_color(self, color: Optional[str]) -> None:
        """Set a custom glow hue (None = theme accent)."""
        if color == self._glow_color:
            return
        self._glow_color = color
        self.update()

    def set_glow_strength(self, strength: float) -> None:
        self._glow_strength = max(0.0, min(1.6, strength))
        self.update()

    def glow_color_value(self) -> str:
        return self._glow_color or self._theme.token("accent")

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._mouse = QPointF(-1000, -1000)
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._mouse = event.pos()
        self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ #
    # Painting
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self._theme.palette()

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # Base surface (drawn explicitly so the glow overlays blend nicely).
        painter.fillPath(path, QColor(palette.surface))

        # Spotlight glow tracking the pointer.
        if self._glow_enabled and self._hover:
            glow = QColor(self.glow_color_value())
            glow.setAlpha(int(30 * self._glow_strength))
            gradient = QRadialGradient(self._mouse, 190)
            gradient.setColorAt(0.0, glow)
            glow_center_outer = QColor(self.glow_color_value())
            glow_center_outer.setAlpha(0)
            gradient.setColorAt(1.0, glow_center_outer)
            painter.fillPath(path, gradient)

        # Border: accent-tinted on hover.
        border_color = QColor(palette.border)
        if self._hover:
            border_color = QColor(rgba(self.glow_color_value(), 0.55))
        painter.setPen(QPen(border_color, 1.0))
        painter.drawPath(path)
        painter.end()
