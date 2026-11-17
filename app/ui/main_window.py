"""Main window: dock navigation, page stack, status bar and shortcuts.

Wires together every page (Dashboard, Project detail, Profiles, Monitor,
Settings), the command palette, the toast host and the global keyboard
shortcut set:

    Ctrl+P  command palette      Ctrl+R  restart current project
    Ctrl+L  focus log search     Ctrl+O  open current project folder
    Ctrl+N  add project          Ctrl+1..5  switch pages
    Ctrl+,  settings             Ctrl+Q  quit
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QShortcut,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.ui.command_palette import CommandPalette
from app.ui.dashboard import DashboardPage
from app.ui.dialogs import AddOrEditProjectDialog, confirm
from app.ui.icons import icon
from app.ui.monitor_view import MonitorPage
from app.ui.profiles_view import ProfilesPage
from app.ui.project_view import ProjectPage
from app.ui.settings_view import SettingsPage
from app.ui.theme import Theme
from app.ui.widgets.badge import Badge
from app.ui.widgets.dock_nav import DockNav
from app.ui.widgets.toast import ToastHost
from app.utils.helpers import format_duration

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """RunHub's top-level window."""

    def __init__(self, app: RunHubApplication) -> None:
        super().__init__()
        self.app = app
        self.setWindowTitle("RunHub — developer workspace manager")
        self.setMinimumSize(1060, 660)
        self.resize(1280, 800)
        self._current_project_id: Optional[str] = None

        self._build_ui()
        self._connect_app_signals()
        self._install_shortcuts()
        self._apply_theme(initial=True)

        # Periodic uptime refresh on the dashboard.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._tick)
        self._refresh_timer.start()

        self.nav.set_active("dashboard")

    # ------------------------------------------------------------------ #
    # UI assembly
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Main content row: dock navigation + page stack.
        content = QWidget()
        content.setObjectName("Root")
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Dock navigation
        self.nav = DockNav()
        self.nav.navigate.connect(self.navigate_to)
        self.nav.theme_toggled.connect(self._toggle_theme)
        self.nav.settings_clicked.connect(lambda: self.navigate_to("settings"))
        root.addWidget(self.nav)

        # Page stack
        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage(self.app)
        self.project_page = ProjectPage(self.app)
        self.profiles_page = ProfilesPage(self.app)
        self.monitor_page = MonitorPage(self.app)
        self.settings_page = SettingsPage(self.app)
        for page in (self.dashboard_page, self.project_page,
                     self.profiles_page, self.monitor_page, self.settings_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.dashboard_page.open_project.connect(self.open_project_view)
        self.dashboard_page.request_add.connect(self._add_project)
        self.dashboard_page.request_scan.connect(self._scan_folder)
        self.dashboard_page.request_edit.connect(self._edit_project)
        self.project_page.go_back.connect(lambda: self.navigate_to("dashboard"))
        self.project_page.request_edit.connect(self._edit_project)

        outer.addWidget(content, 1)

        self.setCentralWidget(central)

        # Status bar — docked as the window footer, full width.
        self._status_bar = QWidget()
        self._status_bar.setObjectName("StatusBar")
        self._status_bar.setFixedHeight(28)
        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(14, 0, 14, 0)
        status_layout.setSpacing(10)
        self._running_badge = Badge("0 running", "#8b93a7")
        status_layout.addWidget(self._running_badge)
        self._hint_label = QLabel("Ctrl+P — command palette")
        self._hint_label.setObjectName("Faint")
        status_layout.addWidget(self._hint_label)
        status_layout.addStretch(1)
        self._cpu_label = QLabel("CPU —")
        self._cpu_label.setObjectName("Faint")
        status_layout.addWidget(self._cpu_label)
        self._ram_label = QLabel("RAM —")
        self._ram_label.setObjectName("Faint")
        status_layout.addWidget(self._ram_label)
        self._version_label = QLabel("RunHub v1.0.0")
        self._version_label.setObjectName("Faint")
        status_layout.addWidget(self._version_label)
        outer.addWidget(self._status_bar)

        # Toasts live inside the central widget.
        self.toast_host = ToastHost(central)

        self.app.monitor.updated.connect(self._on_monitor_stats)
        self.app.monitor.start()

        # Command palette
        self.command_palette = CommandPalette(
            self.app,
            navigate=self.navigate_to,
            open_project=self.open_project_view,
            parent=self,
        )

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def navigate_to(self, page_id: str) -> None:
        """Switch to a page by id (also used by the palette)."""
        mapping = {
            "dashboard": 0, "project": 1, "profiles": 2,
            "monitor": 3, "settings": 4,
        }
        index = mapping.get(page_id, 0)
        self.stack.setCurrentIndex(index)
        self.nav.set_active(page_id if page_id in ("dashboard", "profiles", "monitor", "settings")
                            else "dashboard")
        if page_id == "settings":
            self.settings_page.refresh()

    def open_project_view(self, project_id: str) -> None:
        """Open a project's detail page."""
        project = self.app.get_project(project_id)
        if project is None:
            return
        self._current_project_id = project_id
        self.project_page.show_project(project_id)
        self.stack.setCurrentIndex(1)
        self.nav.set_active("dashboard")

    # ------------------------------------------------------------------ #
    # Palette / shortcut actions
    # ------------------------------------------------------------------ #

    def handle_palette_action(self, action: str) -> None:
        """Actions emitted by the palette (nav/theme/quit/...)."""
        if action == "add":
            self._add_project()
        elif action == "scan":
            self._scan_folder()
        elif action == "theme":
            self._toggle_theme()
        elif action == "reload-plugins":
            self.app.loader.reload(is_enabled=self.app.settings.plugin_enabled, app=self.app)
            self.app.detector.refresh_meta()
            self.app._toast("Plugins reloaded.", "success", "Plugins")
        elif action == "quit":
            self.close()

    def run_project_action(self, project_id: str, action: str) -> None:
        """Project actions emitted by the palette."""
        project = self.app.get_project(project_id)
        if project is None:
            return
        if action == "start":
            self.app.start_project(project)
        elif action == "stop":
            self.app.stop_project(project)
        elif action == "restart":
            self.app.restart_project(project)
        elif action == "folder":
            try:
                self.app.workspace.open_folder(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "Open folder")
        elif action == "vscode":
            try:
                self.app.workspace.open_in_vscode(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "VS Code")
        elif action == "browser":
            self.app.open_browser(project)

    def _current_project(self):
        project = self.app.get_project(self._current_project_id or "")
        if project is not None:
            return project
        # Fall back to the first card on the dashboard.
        projects = self.app.project_list()
        return projects[0] if projects else None

    # ------------------------------------------------------------------ #
    # Project dialogs
    # ------------------------------------------------------------------ #

    def _add_project(self, initial_path: str = "") -> None:
        dialog = AddOrEditProjectDialog(self.app, parent=self)
        if dialog.exec_() == AddOrEditProjectDialog.Accepted:
            data = dialog.project_data()
            try:
                project = self.app.add_project(data)
                self.app._toast(f"Added '{project.name}'.", "success", "Project")
                self.open_project_view(project.id)
            except Exception as exc:
                self.app._toast(str(exc), "error", "Add project")

    def _edit_project(self, project_id: str) -> None:
        project = self.app.get_project(project_id)
        if project is None:
            return
        dialog = AddOrEditProjectDialog(self.app, project, parent=self)
        if dialog.exec_() == AddOrEditProjectDialog.Accepted:
            data = dialog.project_data()
            for key in ("name", "path", "type", "command", "port", "description",
                        "tags", "env", "groups", "favorite", "auto_open_browser",
                        "allow_shell", "color"):
                setattr(project, key, data.get(key, getattr(project, key)))
            self.app.update_project(project)
            self.app._toast("Project updated.", "success", project.name)
            self.project_page.refresh()

    def _scan_folder(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            self, "Choose a folder to scan", str(self.app.config.app_root)
        )
        if not directory:
            return
        self.app._toast("Scanning folder…", "info", "Scan")
        results = self.app.detector.scan_folder(directory, max_depth=2)
        self.dashboard_page.bulk_import(results)

    def _toggle_theme(self) -> None:
        self.app.settings.theme_mode = "light" if Theme.instance().is_dark else "dark"
        Theme.instance().configure(
            self.app.settings.theme_mode,
            self.app.settings.accent_name,
            self.app.settings.font_size,
        )
        self.app.save_settings()

    # ------------------------------------------------------------------ #
    # Signals
    # ------------------------------------------------------------------ #

    def _connect_app_signals(self) -> None:
        self.app.toast_requested.connect(
            lambda message, level, title: self.toast_host.show_toast(message, level, title)
        )
        Theme.instance().changed.connect(lambda: self._apply_theme())

    def _apply_theme(self, initial: bool = False) -> None:
        theme = Theme.instance()
        self.app.settings.theme_mode = theme.mode
        from PyQt5.QtWidgets import QApplication

        qapp = QApplication.instance()
        if qapp is not None:
            qapp.setStyleSheet(theme.stylesheet())
            qapp.setFont(theme.ui_font())
        self.setWindowIcon(icon("logo", theme.token("accent"), 64))
        self._refresh_status_badges()

    # ------------------------------------------------------------------ #
    # Shortcuts
    # ------------------------------------------------------------------ #

    def _install_shortcuts(self) -> None:
        def shortcut(keys: str, callback) -> None:
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(callback)

        shortcut("Ctrl+P", self.command_palette.open)
        shortcut("Ctrl+K", self.command_palette.open)
        shortcut("Ctrl+N", self._add_project)
        shortcut("Ctrl+O", self._open_current_project)
        shortcut("Ctrl+R", self._restart_current_project)
        shortcut("Ctrl+L", self._focus_logs)
        shortcut("Ctrl+F", self._focus_dashboard_search)
        shortcut("Ctrl+1", lambda: self.navigate_to("dashboard"))
        shortcut("Ctrl+2", lambda: self.navigate_to("profiles"))
        shortcut("Ctrl+3", lambda: self.navigate_to("monitor"))
        shortcut("Ctrl+4", lambda: self.navigate_to("settings"))
        shortcut("Ctrl+,", lambda: self.navigate_to("settings"))
        shortcut("Ctrl+Q", self.close)
        shortcut("Esc", self._escape)

    def _open_current_project(self) -> None:
        project = self._current_project()
        if project is None:
            self._add_project()
            return
        try:
            self.app.workspace.open_folder(project.path)
        except Exception as exc:
            self.app._toast(str(exc), "error", "Open folder")

    def _restart_current_project(self) -> None:
        project = self._current_project()
        if project is not None:
            self.app.restart_project(project)

    def _focus_logs(self) -> None:
        if self.stack.currentIndex() != 1:
            project = self._current_project()
            if project is None:
                return
            self.open_project_view(project.id)
        self.project_page.focus_logs()

    def _focus_dashboard_search(self) -> None:
        self.navigate_to("dashboard")
        self.dashboard_page.focus_search()

    def _escape(self) -> None:
        if self.stack.currentIndex() == 1:
            self.navigate_to("dashboard")

    # ------------------------------------------------------------------ #
    # Live status
    # ------------------------------------------------------------------ #

    def _on_monitor_stats(self, stats: dict) -> None:
        cpu = stats.get("cpu", 0.0)
        mem = stats.get("mem_pct", 0.0)
        self._cpu_label.setText(f"CPU {cpu:.0f}%")
        self._ram_label.setText(f"RAM {mem:.0f}%")

    def _tick(self) -> None:
        self.dashboard_page.refresh_visible()
        self._refresh_status_badges()

    def _refresh_status_badges(self) -> None:
        running = self.app.running_count()
        theme = Theme.instance()
        self._running_badge.restyle(
            f"● {running} running" if running else "idle",
            theme.token("success") if running else theme.token("text_faint"),
        )

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:  # noqa: N802
        running = self.app.running_count()
        if running and self.app.settings.confirm_quit_running:
            answer = QMessageBox.question(
                self, "Quit RunHub",
                f"{running} project(s) are still running.\n\n"
                "Quitting will stop their processes. Continue?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.app.shutdown()
        event.accept()
        log.info("RunHub closed.")
