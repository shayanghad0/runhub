"""DockNav: the macOS-dock-inspired expandable navigation rail.

Implements the "expandable tabs" pattern from the design system:

* Tabs show **icon + label** when expanded; icons only when collapsed.
* The active tab expands smoothly (animated label width).
* Hovering the rail expands the active tab; leaving collapses it again.
* ``collapse_all()`` is wired to clicks outside the rail.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import icon
from app.ui.theme import Theme


class DockTab(QPushButton):
    """One navigation entry: icon + (animatable) label."""

    def __init__(self, item_id: str, icon_name: str, label: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self.icon_name = icon_name
        self._label = label
        self._color = color
        self._expanded = False
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)
        self.setObjectName("DockTab")
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 9, 0)
        layout.setSpacing(8)
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)
        self._text_label = QLabel(label)
        self._text_label.setStyleSheet("font-weight: 600; font-size: 12px;")
        self._text_label.setMaximumWidth(0)
        layout.addWidget(self._text_label)
        layout.addStretch(1)

        self._anim: Optional[QPropertyAnimation] = None
        self._paint_icon(color)
        self._apply_state()

    def _paint_icon(self, color: str) -> None:
        self._icon_label.setPixmap(icon(self.icon_name, color, 18).pixmap(18, 18))

    # ------------------------------------------------------------------ #

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self._apply_state()

    def _apply_state(self) -> None:
        theme = Theme.instance()
        if self.isChecked():
            color = theme.token("accent")
            background = theme.token("accent_soft")
            text_color = theme.token("text")
        elif self.underMouse():
            color = theme.token("text")
            background = "transparent"
            text_color = theme.token("text")
        else:
            color = theme.token("text_muted")
            background = "transparent"
            text_color = theme.token("text_muted")
        self._paint_icon(color)
        self.setStyleSheet(
            f"QPushButton#DockTab {{ background: {background}; border: none;"
            f" border-radius: 10px; text-align: left; }}"
            f"QPushButton#DockTab:hover {{ background: {theme.token('surface2')}; }}"
        )
        self._text_label.setStyleSheet(
            f"color: {text_color}; font-weight: 600; font-size: 12px;"
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        if not self.isChecked():
            self._apply_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._apply_state()
        super().leaveEvent(event)

    # ------------------------------------------------------------------ #
    # Expansion
    # ------------------------------------------------------------------ #

    def set_expanded(self, expand: bool) -> None:
        """Animate the label between icon-only and icon+text."""
        if expand == self._expanded:
            return
        self._expanded = expand
        self._text_label.adjustSize()
        target = self._text_label.sizeHint().width() if expand else 0
        if self._anim is None:
            self._anim = QPropertyAnimation(self._text_label, b"maximumWidth", self)
            self._anim.setDuration(170)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.stop()
        self._anim.setStartValue(self._text_label.maximumWidth())
        self._anim.setEndValue(target)
        self._anim.start()


class DockNav(QWidget):
    """Left navigation rail with the app logo and theme/settings buttons."""

    navigate = pyqtSignal(str)          # page id
    theme_toggled = pyqtSignal()
    settings_clicked = pyqtSignal()

    WIDTH = 66

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DockRail")
        self.setFixedWidth(self.WIDTH)
        self._tabs: List[DockTab] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(6)

        # Logo
        self._logo = QLabel()
        self._logo.setFixedSize(36, 36)
        self._logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._logo)
        layout.addSpacing(10)

        self._add_tab("dashboard", "grid", "Dashboard", "#8b93a7")
        self._add_tab("profiles", "layers", "Profiles", "#8b93a7")
        self._add_tab("monitor", "activity", "Monitor", "#8b93a7")
        layout.addStretch(1)

        # Bottom actions
        self._theme_button = QPushButton()
        self._theme_button.setObjectName("Ghost")
        self._theme_button.setFixedSize(42, 42)
        self._theme_button.setCursor(Qt.PointingHandCursor)
        self._theme_button.setToolTip("Toggle theme (dark / light)")
        self._theme_button.clicked.connect(self.theme_toggled.emit)
        layout.addWidget(self._theme_button)

        self._settings_button = QPushButton()
        self._settings_button.setObjectName("Ghost")
        self._settings_button.setFixedSize(42, 42)
        self._settings_button.setCursor(Qt.PointingHandCursor)
        self._settings_button.setToolTip("Settings (Ctrl+,)")
        self._settings_button.clicked.connect(self.settings_clicked.emit)
        layout.addWidget(self._settings_button)

        self._refresh_static_icons()
        Theme.instance().changed.connect(self._refresh_static_icons)

    # ------------------------------------------------------------------ #

    def _add_tab(self, item_id: str, icon_name: str, label: str, color: str) -> None:
        tab = DockTab(item_id, icon_name, label, color)
        tab.clicked.connect(lambda _, tid=item_id: self.navigate.emit(tid))
        self._tabs.append(tab)
        # Insert before the stretch + bottom actions.
        self.layout().insertWidget(self.layout().count() - 2, tab)

    def _refresh_static_icons(self) -> None:
        theme = Theme.instance()
        self._logo.setPixmap(icon("logo", theme.token("accent"), 30).pixmap(30, 30))
        self._theme_button.setIcon(icon("moon" if theme.is_dark else "sun",
                                        theme.token("text_muted"), 18))
        self._settings_button.setIcon(icon("sliders", theme.token("text_muted"), 18))
        for tab in self._tabs:
            tab._apply_state()  # noqa: SLF001 - same module styling hook

    # ------------------------------------------------------------------ #

    def set_active(self, page_id: str) -> None:
        """Select a page and expand its label; collapse the others."""
        for tab in self._tabs:
            tab.set_active(tab.item_id == page_id)
            tab.set_expanded(tab.isChecked())

    def collapse_all(self) -> None:
        """Collapse every tab to icon-only (called on outside clicks)."""
        for tab in self._tabs:
            tab.set_expanded(False)

    def expand_active(self) -> None:
        """Re-expand the active tab's label."""
        for tab in self._tabs:
            tab.set_expanded(tab.isChecked())
