"""Toast notifications.

Non-modal, auto-dismissing notifications stacked in the top-right corner
of the main window — the RunHub equivalent of the shadcn "badge delta"
feedback pattern for background events (port detected, process crashed,
profile started…).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import icon
from app.ui.theme import Theme

log = logging.getLogger(__name__)

LEVEL_ICONS = {"info": "info", "success": "check", "warn": "warn", "error": "x_circle"}
LEVEL_DURATION_MS = {"info": 3800, "success": 3200, "warn": 5000, "error": 6500}


class Toast(QWidget):
    """One notification card (rounded, icon + title + message)."""

    WIDTH = 330

    def __init__(self, message: str, level: str = "info", title: str = "", parent=None) -> None:
        super().__init__(parent)
        self._theme = Theme.instance()
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._level = level if level in LEVEL_ICONS else "info"
        color_map = {
            "info": self._theme.token("info"),
            "success": self._theme.token("success"),
            "warn": self._theme.token("warning"),
            "error": self._theme.token("danger"),
        }
        accent = color_map[self._level]

        self.setStyleSheet(
            f"QWidget {{ background: {self._theme.token('surface')};"
            f" border: 1px solid {self._theme.token('border_strong')}; border-radius: 12px; }}"
            f"QLabel {{ background: transparent; border: none; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(icon(LEVEL_ICONS[self._level], accent, 18).pixmap(18, 18))
        icon_label.setFixedSize(20, 20)
        icon_label.setAlignment(Qt.AlignTop)
        row.addWidget(icon_label)

        text_column = QWidget()
        text_layout = QHBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        title_text = title or self._level.capitalize()
        title_label = QLabel(title_text)
        title_label.setStyleSheet(
            f"color: {self._theme.token('text')}; font-weight: 600; font-size: 12px;"
        )
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setStyleSheet(
            f"color: {self._theme.token('text_muted')}; font-size: 11px;"
        )
        column_box = QVBoxLayout()
        column_box.setContentsMargins(0, 0, 0, 0)
        column_box.setSpacing(1)
        column_box.addWidget(title_label)
        column_box.addWidget(message_label)
        text_layout.addLayout(column_box)
        row.addWidget(text_column, 1)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background: transparent; border: none; }}"
            f"QProgressBar::chunk {{ background: {accent}; border-radius: 1px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(row)
        outer.addWidget(self._progress)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.setInterval(50)

    # ------------------------------------------------------------------ #

    def start(self, duration_ms: int) -> None:
        """Animate in, count down, animate out and self-destruct."""
        self.show()
        fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        fade_in.setDuration(180)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start()

        self._duration = duration_ms
        self._elapsed = 0
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed += self._timer.interval()
        remaining = max(0, 100 - int(self._elapsed / self._duration * 100))
        self._progress.setValue(remaining)
        if self._elapsed >= self._duration:
            self.dismiss()

    def dismiss(self) -> None:
        self._timer.stop()
        fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        fade_out.setDuration(200)
        fade_out.setStartValue(self._effect.opacity())
        fade_out.setEndValue(0.0)
        try:
            fade_out.finished.disconnect()
        except TypeError:
            pass
        fade_out.finished.connect(self.deleteLater)
        fade_out.start()


class ToastHost(QWidget):
    """Manages a vertical stack of :class:`Toast` widgets."""

    MAX_TOASTS = 4

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._toasts: List[Toast] = []

    def show_toast(self, message: str, level: str = "info", title: str = "") -> None:
        """Add a toast (dropping the oldest beyond MAX_TOASTS)."""
        try:
            toast = Toast(message, level, title, self)
            self._toasts.append(toast)
            while len(self._toasts) > self.MAX_TOASTS:
                oldest = self._toasts.pop(0)
                oldest.deleteLater()
            self._reposition()
            toast.start(LEVEL_DURATION_MS.get(level, 3800))
            toast.destroyed.connect(lambda: self._forget(toast))
        except Exception:  # never let notifications break the app
            log.exception("toast failed: %s", message)

    def _forget(self, toast: Toast) -> None:
        try:
            self._toasts.remove(toast)
        except ValueError:
            pass
        self._reposition()

    def _reposition(self) -> None:
        window = self.parentWidget()
        if window is None:
            return
        margin = 16
        y = margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            height = toast.sizeHint().height()
            toast.move(window.width() - toast.WIDTH - margin, y)
            toast.raise_()
            y += height + 10
        self.resize(window.width(), window.height())
