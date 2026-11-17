"""Command palette (Ctrl+P / Ctrl+K).

Frameless popup with fuzzy search over commands and projects:

* navigation between pages, theme toggle, add project, reload plugins,
* per-project actions: open, start, stop, restart, folder, VS Code, browser,
* arrow keys to move, Enter to run, Esc / outside click to close.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.ui.icons import icon
from app.ui.theme import Theme
from app.utils.helpers import fuzzy_score

log = logging.getLogger(__name__)


class Command:
    """One palette entry."""

    __slots__ = ("title", "subtitle", "icon_name", "icon_color", "handler", "section")

    def __init__(self, title: str, subtitle: str, icon_name: str,
                 handler: Callable[[], None], icon_color: str = "",
                 section: str = "") -> None:
        self.title = title
        self.subtitle = subtitle
        self.icon_name = icon_name
        self.icon_color = icon_color
        self.handler = handler
        self.section = section


class CommandPalette(QDialog):
    """The RunHub command palette."""

    def __init__(self, app: RunHubApplication, navigate: Callable[[str], None],
                 open_project: Callable[[str], None], parent=None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.app = app
        self._navigate = navigate
        self._open_project = open_project
        self._commands: List[Command] = []
        self._filtered: List[Command] = []

        self.setMinimumWidth(600)
        self.setMaximumWidth(600)
        self.setObjectName("PaletteOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search_icon = QLabel()
        search_row.addWidget(self._search_icon)
        self._search = QLineEdit()
        self._search.setObjectName("Search")
        self._search.setPlaceholderText("Type a command or project name…")
        self._search.textChanged.connect(self._apply_filter)
        self._search.returnPressed.connect(self._run_selected)
        self._search.installEventFilter(self)
        search_row.addWidget(self._search, 1)
        hint = QLabel("esc")
        hint.setObjectName("Faint")
        search_row.addWidget(hint)
        layout.addLayout(search_row)

        self._list = QListWidget()
        self._list.setFixedHeight(380)
        self._list.itemActivated.connect(lambda _item: self._run_selected())
        self._list.currentRowChanged.connect(self._update_detail)
        layout.addWidget(self._list)

        self._detail = QLabel("")
        self._detail.setObjectName("Faint")
        layout.addWidget(self._detail)

        self._opacity_effect = self.graphicsEffect()
        self._animation: Optional[QPropertyAnimation] = None
        self._theme = Theme.instance()
        self._refresh_static_icons()

    # ------------------------------------------------------------------ #

    def _refresh_static_icons(self) -> None:
        theme = Theme.instance()
        self._search_icon.setPixmap(icon("search", theme.token("text_muted"), 16).pixmap(16, 16))

    def open(self) -> None:
        """Rebuild commands, position over the main window and show."""
        self._build_commands()
        self._apply_filter()
        window = self.parentWidget()
        if window is not None:
            x = window.x() + (window.width() - self.width()) // 2
            y = window.y() + int(window.height() * 0.16)
            self.move(x, y)
        self._search.clear()
        self._search.setFocus()
        self.show()

    # ------------------------------------------------------------------ #
    # Command registry
    # ------------------------------------------------------------------ #

    def _build_commands(self) -> None:
        app = self.app
        theme = Theme.instance()
        commands: List[Command] = []

        # Navigation
        for page_id, label in (("dashboard", "Go to Dashboard"),
                               ("profiles", "Go to Profiles"),
                               ("monitor", "Go to System Monitor"),
                               ("settings", "Go to Settings")):
            icon_name = {"dashboard": "grid", "profiles": "layers",
                         "monitor": "activity", "settings": "sliders"}[page_id]
            commands.append(Command(
                label, "Navigation", icon_name,
                lambda pid=page_id: self._navigate(pid),
                theme.token("accent"), "Navigate",
            ))

        commands.append(Command("Add new project…", "Projects", "plus",
                                lambda: self._request("add"), theme.token("accent"), "Actions"))
        commands.append(Command("Scan folder for projects…", "Projects", "scan",
                                lambda: self._request("scan"), theme.token("accent"), "Actions"))
        commands.append(Command("Toggle dark / light mode", "Appearance", "moon",
                                lambda: self._request("theme"), theme.token("warning"), "Actions"))
        commands.append(Command("Reload plugins", "Advanced", "restart",
                                lambda: self._request("reload-plugins"),
                                theme.token("info"), "Actions"))
        commands.append(Command("Quit RunHub", "Advanced", "power",
                                lambda: self._request("quit"), theme.token("danger"), "Actions"))

        # Per-project actions
        for project in app.project_list():
            meta = app.detector.meta_for(project.type)
            color = meta["color"]
            status = app.status_of(project)
            running = status.is_active
            commands.append(Command(
                f"Open  {project.name}",
                f"{meta['label']}  •  {project.path}",
                meta["icon"],
                lambda pid=project.id: self._open_project_safe(pid),
                color, "Projects",
            ))
            if running:
                commands.append(Command(
                    f"Stop  {project.name}", f"{status.label}  •  :{project.port or '—'}",
                    "stop", lambda pid=project.id: self._project_action(pid, "stop"),
                    theme.token("danger"), "Project actions",
                ))
            else:
                commands.append(Command(
                    f"Start  {project.name}",
                    f"{meta['label']}  •  {project.command or 'no command'}",
                    "play", lambda pid=project.id: self._project_action(pid, "start"),
                    theme.token("success"), "Project actions",
                ))
            commands.append(Command(
                f"Restart  {project.name}", "Project actions", "restart",
                lambda pid=project.id: self._project_action(pid, "restart"),
                theme.token("warning"), "Project actions",
            ))
            commands.append(Command(
                f"Open folder  {project.name}", project.path, "folder_open",
                lambda pid=project.id: self._project_action(pid, "folder"),
                theme.token("info"), "Project actions",
            ))
            if app.workspace.vscode_installed():
                commands.append(Command(
                    f"Open in VS Code  {project.name}", project.path, "editor",
                    lambda pid=project.id: self._project_action(pid, "vscode"),
                    "#4b8bbe", "Project actions",
                ))
            if project.port:
                commands.append(Command(
                    f"Open browser  {project.name}", f"http://localhost:{project.port}",
                    "globe", lambda pid=project.id: self._project_action(pid, "browser"),
                    theme.token("info"), "Project actions",
                ))

        self._commands = commands

    def _request(self, action: str) -> None:
        window = self.parentWidget()
        self.accept()
        if window is not None and hasattr(window, "handle_palette_action"):
            window.handle_palette_action(action)  # type: ignore[attr-defined]

    def _open_project_safe(self, project_id: str) -> None:
        self.accept()
        self._open_project(project_id)

    def _project_action(self, project_id: str, action: str) -> None:
        window = self.parentWidget()
        self.accept()
        if window is not None and hasattr(window, "run_project_action"):
            window.run_project_action(project_id, action)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Filtering / running
    # ------------------------------------------------------------------ #

    def _apply_filter(self, *_args) -> None:
        query = self._search.text().strip()
        scored: List[Tuple[int, Command]] = []
        for command in self._commands:
            haystack = f"{command.title} {command.subtitle} {command.section}"
            score = fuzzy_score(query, haystack)
            if score > 0:
                scored.append((score, command))
        scored.sort(key=lambda pair: -pair[0])
        self._filtered = [command for _, command in scored[:40]]

        self._list.blockSignals(True)
        self._list.clear()
        theme = Theme.instance()
        current_section = None
        for command in self._filtered:
            if command.section and command.section != current_section:
                separator = QListWidgetItem(command.section.upper())
                separator.setFlags(Qt.NoItemFlags)
                separator.setForeground(QColor(theme.token("text_faint")))
                separator.setData(Qt.UserRole, None)
                self._list.addItem(separator)
                current_section = command.section
            item = QListWidgetItem(command.title)
            item.setData(Qt.UserRole, command)
            item.setToolTip(command.subtitle)
            color = command.icon_color or theme.token("accent")
            item.setIcon(icon(command.icon_name, color, 15))
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._list.count() and self._filtered:
            self._list.setCurrentRow(1 if self._list.item(0).flags() == Qt.NoItemFlags else 0)
        self._list.setFixedHeight(min(380, max(60, 26 * self._list.count() + 10)))
        self.adjustSize()

    def _update_detail(self, row: int) -> None:
        item = self._list.item(row)
        command = item.data(Qt.UserRole) if item else None
        self._detail.setText(command.subtitle if command else "")

    def _run_selected(self) -> None:
        item = self._list.currentItem()
        command = item.data(Qt.UserRole) if item else None
        if command is None:
            return
        try:
            command.handler()
        except Exception:
            log.exception("Palette command failed: %s", command.title)
        if not self._search.text().strip():
            self.close()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._search and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                row = self._list.currentRow()
                step = 1 if key == Qt.Key_Down else -1
                count = self._list.count()
                if count:
                    self._list.setCurrentRow(max(0, min(count - 1, row + step)))
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
