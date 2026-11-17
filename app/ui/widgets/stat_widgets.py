"""StatTile and small label helpers for dashboard/monitor headers."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.icons import icon
from app.ui.theme import Theme


class StatTile(QFrame):
    """Icon + title + big value (+ sub label) tile used in metric rows."""

    def __init__(self, icon_name: str, title: str, color: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._icon_name = icon_name
        self._title = title
        self._color_name = color
        self._theme = Theme.instance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(18, 18)
        top.addWidget(self._icon_label)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("Muted")
        top.addWidget(self._title_label)
        top.addStretch(1)
        layout.addLayout(top)

        self._value_label = QLabel("—")
        self._value_label.setStyleSheet("font-size: 21px; font-weight: 700;")
        layout.addWidget(self._value_label)

        self._sub_label = QLabel("")
        self._sub_label.setObjectName("Faint")
        layout.addWidget(self._sub_label)

        Theme.instance().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        theme = self._theme
        color = self._color_name or theme.token("accent")
        self._icon_label.setPixmap(icon(self._icon_name, color, 16).pixmap(16, 16))

    def set_value(self, value: str, sub: str = "") -> None:
        self._value_label.setText(value)
        self._sub_label.setText(sub)
