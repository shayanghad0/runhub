"""Project detail view: header, actions, info cards and the live console.

Layout: a header row (back button, type icon, name, status, action bar),
a horizontal splitter with the info column (details, stats, URLs,
environment, plugin tools) on the left and the LogConsole on the right.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.models.project import Project, ProjectStatus
from app.ui.dialogs import AddOrEditProjectDialog, confirm
from app.ui.icons import icon
from app.ui.theme import Theme, rgba
from app.ui.widgets.badge import Badge
from app.ui.widgets.log_console import LogConsole
from app.ui.widgets.spotlight_card import SpotlightCard
from app.utils.helpers import format_duration, format_timestamp

log = logging.getLogger(__name__)


def _card(title: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("Heading")
    layout.addWidget(label)
    return frame


class ProjectPage(QWidget):
    """Detail page for one project."""

    go_back = pyqtSignal()
    request_edit = pyqtSignal(str)   # project_id

    def __init__(self, app: RunHubApplication, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._project_id: Optional[str] = None
        self._build()
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self.app.project_status_changed.connect(self._on_status_changed)
        self.app.project_updated.connect(self._on_project_updated)
        self.app.logs.urls_detected.connect(self._on_urls)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 10)
        outer.setSpacing(10)

        # Header ---------------------------------------------------------- #
        self._header = QWidget()
        header_layout = QVBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        back = QToolButton()
        back.setToolTip("Back to dashboard (Esc)")
        back.clicked.connect(self.go_back.emit)
        self._back_button = back
        top_row.addWidget(back)

        self._type_icon = QLabel()
        self._type_icon.setFixedSize(30, 30)
        top_row.addWidget(self._type_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self._name_label = QLabel("")
        self._name_label.setObjectName("Title")
        title_box.addWidget(self._name_label)
        self._path_label = QLabel("")
        self._path_label.setObjectName("Faint")
        title_box.addWidget(self._path_label)
        top_row.addLayout(title_box, 1)

        self._status_badge = Badge("Stopped", "#8b93a7")
        top_row.addWidget(self._status_badge)
        self._menu_button = QToolButton()
        self._menu_button.setToolTip("More actions")
        self._menu_button.clicked.connect(self._show_menu)
        top_row.addWidget(self._menu_button)
        header_layout.addLayout(top_row)

        # Action bar
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._start_button = QPushButton("Start")
        self._start_button.setObjectName("Primary")
        self._start_button.setFixedHeight(34)
        self._start_button.clicked.connect(self._toggle_running)
        actions.addWidget(self._start_button)

        self._restart_button = QPushButton(" Restart")
        self._restart_button.setIcon(icon("restart", "#8b93a7", 14))
        self._restart_button.clicked.connect(self._restart)
        actions.addWidget(self._restart_button)

        self._folder_button = QPushButton(" Folder")
        self._folder_button.setIcon(icon("folder_open", "#8b93a7", 14))
        self._folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self._folder_button)

        self._vscode_button = QPushButton(" VS Code")
        self._vscode_button.setIcon(icon("editor", "#8b93a7", 14))
        self._vscode_button.clicked.connect(self._open_vscode)
        actions.addWidget(self._vscode_button)

        self._terminal_button = QPushButton(" Terminal")
        self._terminal_button.setIcon(icon("terminal", "#8b93a7", 14))
        self._terminal_button.clicked.connect(self._open_terminal)
        actions.addWidget(self._terminal_button)

        self._browser_button = QPushButton(" Open browser")
        self._browser_button.setIcon(icon("globe", "#8b93a7", 14))
        self._browser_button.clicked.connect(self._open_browser)
        actions.addWidget(self._browser_button)

        self._edit_button = QPushButton(" Edit")
        self._edit_button.setIcon(icon("pencil", "#8b93a7", 14))
        self._edit_button.clicked.connect(self._edit)
        actions.addWidget(self._edit_button)
        actions.addStretch(1)

        # Plugin tool commands are injected here by refresh().
        self._tools_row = QHBoxLayout()
        self._tools_row.setSpacing(6)
        header_layout.addLayout(actions)
        header_layout.addLayout(self._tools_row)

        outer.addWidget(self._header)

        # Splitter --------------------------------------------------------- #
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_inner = QWidget()
        left_column = QVBoxLayout(left_inner)
        left_column.setContentsMargins(0, 0, 6, 0)
        left_column.setSpacing(10)

        # Details card
        details = _card("Details")
        form = QVBoxLayout()
        form.setSpacing(5)
        self._detail_rows: Dict[str, QLabel] = {}
        for key, label in (
            ("type", "Type"), ("port", "Port"), ("command", "Command"),
            ("created", "Created"), ("runs", "Total runs"),
            ("last_start", "Last started"), ("last_exit", "Last exit code"),
            ("tags", "Tags"),
        ):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("Muted")
            name.setFixedWidth(110)
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(name)
            row.addWidget(value, 1)
            self._detail_rows[key] = value
            form.addLayout(row)
        details.layout().addLayout(form)
        left_column.addWidget(details)

        # URLs card
        self._urls_card = _card("Detected URLs")
        self._urls_box = QVBoxLayout()
        self._urls_box.setSpacing(4)
        self._urls_card.layout().addLayout(self._urls_box)
        left_column.addWidget(self._urls_card)

        # Environment card
        self._env_card = _card("Environment")
        self._env_table = QTableWidget(0, 2)
        self._env_table.horizontalHeader().setStretchLastSection(True)
        self._env_table.setColumnWidth(0, 170)
        self._env_table.setFixedHeight(110)
        self._env_table.horizontalHeader().setVisible(False)
        self._env_table.verticalHeader().setVisible(False)
        self._env_card.layout().addWidget(self._env_table)
        left_column.addWidget(self._env_card)

        # Profiles card
        self._profiles_card = _card("Profiles")
        self._profiles_box = QHBoxLayout()
        self._profiles_card.layout().addLayout(self._profiles_box)
        left_column.addWidget(self._profiles_card)
        left_column.addStretch(1)

        left_scroll.setWidget(left_inner)
        left_layout.addWidget(left_scroll)
        self._splitter.addWidget(left)

        # Right: log console
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        console_header = QHBoxLayout()
        console_title = QLabel("Live console")
        console_title.setObjectName("Heading")
        console_header.addWidget(console_title)
        console_header.addStretch(1)
        self._exit_label = QLabel("")
        self._exit_label.setObjectName("Faint")
        console_header.addWidget(self._exit_label)
        right_layout.addLayout(console_header)
        self._console = LogConsole()
        right_layout.addWidget(self._console, 1)
        self._splitter.addWidget(right)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([360, 640])
        outer.addWidget(self._splitter, 1)

    # ------------------------------------------------------------------ #

    def show_project(self, project_id: str) -> None:
        """Switch the page to a project."""
        project = self.app.get_project(project_id)
        if project is None:
            return
        self._project_id = project_id
        self._console.attach(project_id, self.app.logs)
        self.refresh()
        self._uptime_timer.start()
        theme = Theme.instance()
        self._back_button.setIcon(icon("chevron_left", theme.token("text_muted"), 18))
        self._menu_button.setIcon(icon("list", theme.token("text_muted"), 18))

    def refresh(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project is None:
            return
        theme = Theme.instance()
        meta = self.app.detector.meta_for(project.type)
        status = self.app.status_of(project)

        self._name_label.setText(project.name)
        self._path_label.setText(project.path)
        self._type_icon.setPixmap(icon(meta["icon"], meta["color"], 24).pixmap(24, 24))
        self._status_badge.restyle(status.label, theme.status_color(status.value))
        self._menu_button.setIcon(icon("list", theme.token("text_muted"), 18))

        running = status.is_active
        self._start_button.setText("Stop" if running else "Start")
        self._start_button.setObjectName(
            "Danger" if running and status != ProjectStatus.STOPPING else "Primary"
        )
        self._start_button.style().unpolish(self._start_button)
        self._start_button.style().polish(self._start_button)

        # Detail rows
        rows = self._detail_rows
        rows["type"].setText(meta["label"])
        rows["port"].setText(f"localhost:{project.port}" if project.port else "auto / none")
        rows["command"].setText(project.command or "—")
        rows["created"].setText(format_timestamp(project.created_at))
        rows["runs"].setText(str(project.run_count))
        rows["last_start"].setText(format_timestamp(project.last_started_at))
        rows["last_exit"].setText(
            str(project.last_exit_code) if project.last_exit_code is not None else "—"
        )
        rows["tags"].setText(", ".join(project.tags) or "—")

        # URLs card
        while self._urls_box.count():
            item = self._urls_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        urls = []
        if project.port:
            urls.append(f"http://localhost:{project.port}")
        buffer = self.app.logs.log_for(project.id)
        for url in buffer.live_urls:
            if url not in urls:
                urls.append(url)
        if urls:
            for url in urls[:5]:
                row = QHBoxLayout()
                row.setSpacing(6)
                link = QLabel(url)
                link.setStyleSheet(f"color: {theme.token('info')};")
                link.setTextInteractionFlags(Qt.TextSelectableByMouse)
                row.addWidget(link, 1)
                open_button = QToolButton()
                open_button.setToolTip("Open in browser")
                open_button.setIcon(icon("external", theme.token("text_muted"), 13))
                open_button.clicked.connect(lambda _, u=url: self.app.browser.open_url(u))
                row.addWidget(open_button)
                copy_button = QToolButton()
                copy_button.setToolTip("Copy URL")
                copy_button.setIcon(icon("copy", theme.token("text_muted"), 13))
                copy_button.clicked.connect(lambda _, u=url: self.app.browser.copy_url(u))
                row.addWidget(copy_button)
                container = QWidget()
                container.setLayout(row)
                self._urls_box.addWidget(container)
        else:
            self._urls_box.addWidget(QLabel("No URLs detected yet — start the project."))

        # Environment
        self._env_table.setRowCount(0)
        for key, value in sorted(project.env.items()):
            row_index = self._env_table.rowCount()
            self._env_table.insertRow(row_index)
            self._env_table.setItem(row_index, 0, QTableWidgetItem(key))
            self._env_table.setItem(row_index, 1, QTableWidgetItem(value))
        if not project.env:
            self._env_table.setRowCount(1)
            self._env_table.setItem(0, 0, QTableWidgetItem("(none)"))

        # Profiles
        while self._profiles_box.count():
            item = self._profiles_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for profile in self.app.profile_list():
            if project.id in profile.project_ids:
                chip = QLabel(profile.name)
                chip.setStyleSheet(
                    f"color: {profile.color}; background: {rgba(profile.color, 0.13)};"
                    "border-radius: 9px; padding: 2px 10px; font-size: 10px; font-weight: 600;"
                )
                self._profiles_box.addWidget(chip)
        if self._profiles_box.count() == 0:
            self._profiles_box.addWidget(QLabel("Not in any profile."))

        # Plugin tool commands
        self._refresh_tools(project)

    def _refresh_tools(self, project: Project) -> None:
        """Render plugin-contributed CommandSpecs as buttons."""
        while self._tools_row.count():
            item = self._tools_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        specs = self.app.detector.commands_for(project.type, project)
        if not specs:
            return
        theme = Theme.instance()
        label = QLabel("Tools:")
        label.setObjectName("Muted")
        self._tools_row.addWidget(label)
        for spec in specs[:5]:
            button = QPushButton(f" {spec.label}")
            button.setIcon(icon(spec.icon or "terminal", theme.token("text_muted"), 13))
            button.setToolTip(spec.command + ("  (asks for confirmation)" if spec.confirm else ""))
            button.clicked.connect(lambda _, s=spec: self._run_tool(project, s))
            self._tools_row.addWidget(button)
        self._tools_row.addStretch(1)

    # ------------------------------------------------------------------ #

    def _run_tool(self, project: Project, spec) -> None:
        if spec.confirm and not confirm(
            self, spec.label, f"Run '{spec.command}' for '{project.name}'?", danger=True
        ):
            return
        self.app.processes.run_aux(project, spec)

    def _toggle_running(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project is None:
            return
        if self.app.status_of(project).is_active:
            if self.app.settings.confirm_stop and not confirm(
                self, "Stop project", f"Stop '{project.name}'?"
            ):
                return
            self.app.stop_project(project)
        else:
            self.app.start_project(project)

    def _restart(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project:
            self.app.restart_project(project)

    def _open_folder(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project:
            try:
                self.app.workspace.open_folder(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "Open folder")

    def _open_vscode(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project:
            try:
                self.app.workspace.open_in_vscode(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "VS Code")

    def _open_terminal(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project:
            try:
                self.app.workspace.open_terminal(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "Terminal")

    def _open_browser(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project:
            self.app.open_browser(project)

    def _edit(self) -> None:
        if self._project_id:
            self.request_edit.emit(self._project_id)

    def _show_menu(self) -> None:
        project = self.app.get_project(self._project_id or "")
        if project is None:
            return
        menu = QMenu(self)
        menu.addAction(icon("star_outline", "#8b93a7"),
                       "Favorite" if not project.favorite else "Unfavorite",
                       lambda: self.app.toggle_favorite(project.id))
        menu.addAction(icon("copy", "#8b93a7"), "Copy command",
                       lambda: self._copy_command(project))
        menu.addSeparator()
        for spec in self.app.detector.commands_for(project.type, project):
            menu.addAction(icon(spec.icon or "terminal", "#8b93a7"),
                           spec.label, lambda s=spec: self._run_tool(project, s))
        menu.addSeparator()
        menu.addAction(icon("trash", "#f87171"), "Delete project…",
                       lambda: self._delete(project))
        menu.exec_(self._menu_button.mapToGlobal(self._menu_button.rect().bottomLeft()))

    def _copy_command(self, project: Project) -> None:
        QApplication_clipboard(project.command)
        self.app._toast(project.command or "(no command)", "success", "Copied")

    def _delete(self, project: Project) -> None:
        if confirm(self, "Delete project",
                   f"Delete '{project.name}'? Files on disk are not touched.", danger=True):
            self.app.delete_project(project.id)
            self.go_back.emit()

    # ------------------------------------------------------------------ #
    # Live updates
    # ------------------------------------------------------------------ #

    def _on_status_changed(self, project_id: str, status_value: str) -> None:
        if project_id != self._project_id:
            return
        self.refresh()
        if status_value == "running":
            self._exit_label.setText("")

    def _on_project_updated(self, project_id: str) -> None:
        if project_id == self._project_id:
            self.refresh()

    def _on_urls(self, project_id: str, urls) -> None:
        if project_id == self._project_id:
            self.refresh()

    def _tick_uptime(self) -> None:
        if not self._project_id:
            return
        uptime = self.app.processes.uptime_for(self._project_id)
        if uptime > 1:
            handle = self.app.processes.handle_for(self._project_id)
            if handle is not None and not self._exit_label.text().startswith("up"):
                self._exit_label.setText(f"up {format_duration(uptime)}")

    def focus_logs(self) -> None:
        """Ctrl+L: focus the console search box."""
        self._console.focus_search()


def QApplication_clipboard(text: str) -> None:
    """Copy text to the clipboard (helper used by the header menu)."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.clipboard().setText(text)
