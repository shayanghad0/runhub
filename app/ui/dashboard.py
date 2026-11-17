"""Dashboard page: the project card grid.

Implements the "Project Dashboard" feature:

* cards show name, type icon, status badge, port, action buttons
  (Start/Stop, Restart, Open Folder, Open Browser) and open the detail
  view on click,
* cards use the SpotlightCard glow effect and a pulsing status dot,
* live search, status/type filter chips, sorting, grid/list toggle,
* empty state with Add Project + Scan Folder actions.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.models.project import Project, ProjectStatus, type_meta
from app.ui.dialogs import BulkImportDialog, confirm
from app.ui.icons import icon
from app.ui.theme import Theme
from app.ui.widgets.badge import Badge, StatusDot
from app.ui.widgets.flow_layout import FlowLayout
from app.ui.widgets.spotlight_card import SpotlightCard
from app.utils.filesystem import human_size

log = logging.getLogger(__name__)

ACTION_ICONS = {
    "start": "play", "stop": "stop", "restart": "restart",
    "folder": "folder_open", "browser": "globe",
}


class ProjectCard(SpotlightCard):
    """One project card on the dashboard."""

    action_requested = pyqtSignal(str, str)   # project_id, action name
    opened = pyqtSignal(str)                  # project_id

    CARD_WIDTH = 302
    CARD_HEIGHT = 196

    def __init__(self, app: RunHubApplication, project: Project, parent=None) -> None:
        super().__init__(parent, radius=14, glow=True)
        self.app = app
        self._project_id = project.id
        self._project = project
        self._status: ProjectStatus = app.status_of(project)
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._build()
        if project.color:
            self.set_glow_color(project.color)
        self.refresh(project)

    # ------------------------------------------------------------------ #

    @property
    def project_id(self) -> str:
        return self._project_id

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top row: type icon + favorite + status badge
        top = QHBoxLayout()
        top.setSpacing(8)
        self._type_icon = QLabel()
        self._type_icon.setFixedSize(24, 24)
        top.addWidget(self._type_icon)
        self._type_label = QLabel()
        self._type_label.setObjectName("Faint")
        top.addWidget(self._type_label)
        top.addStretch(1)
        self._favorite = QToolButton()
        self._favorite.setObjectName("Flat")
        self._favorite.setFixedSize(26, 26)
        self._favorite.setCursor(Qt.PointingHandCursor)
        self._favorite.clicked.connect(self._toggle_favorite)
        top.addWidget(self._favorite)
        layout.addLayout(top)

        # Name + status dot
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._dot = StatusDot("#8b93a7", diameter=9)
        name_row.addWidget(self._dot)
        self._name_label = QLabel()
        self._name_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._name_label.setWordWrap(False)
        name_row.addWidget(self._name_label, 1)
        layout.addLayout(name_row)

        # Path
        self._path_label = QLabel()
        self._path_label.setObjectName("Faint")
        layout.addWidget(self._path_label)

        # Chips row: status badge + port
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._status_badge = Badge("Stopped", "#8b93a7")
        chips.addWidget(self._status_badge)
        self._port_badge = Badge("—", "#8b93a7")
        chips.addWidget(self._port_badge)
        self._uptime_label = QLabel("")
        self._uptime_label.setObjectName("Faint")
        chips.addWidget(self._uptime_label, 1)
        layout.addLayout(chips)

        layout.addStretch(1)

        # Actions row
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._primary = QPushButton("Start")
        self._primary.setObjectName("Primary")
        self._primary.setFixedHeight(30)
        self._primary.setCursor(Qt.PointingHandCursor)
        self._primary.clicked.connect(lambda: self._emit("start" if not self._status.is_active else "stop"))
        actions.addWidget(self._primary)
        for action in ("restart", "folder", "browser"):
            button = QToolButton()
            button.setFixedSize(30, 30)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(
                {"restart": "Restart", "folder": "Open folder",
                 "browser": "Open browser"}[action]
            )
            button.clicked.connect(lambda _, a=action: self._emit(a))
            setattr(self, f"_{action}_button", button)
            actions.addWidget(button)
        actions.addStretch(1)
        self._open_button = QToolButton()
        self._open_button.setFixedSize(30, 30)
        self._open_button.setCursor(Qt.PointingHandCursor)
        self._open_button.setToolTip("Open project details")
        self._open_button.clicked.connect(lambda: self.opened.emit(self._project_id))
        actions.addWidget(self._open_button)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #

    def _emit(self, action: str) -> None:
        self.action_requested.emit(self._project_id, action)

    def _toggle_favorite(self) -> None:
        self.app.toggle_favorite(self._project_id)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        project = self.app.get_project(self._project_id)
        if project is None:
            return
        menu.addAction(icon("external", "#8b93a7"), "Open details",
                       lambda: self.opened.emit(self._project_id))
        menu.addSeparator()
        menu.addAction(icon("editor", "#8b93a7"), "Open in VS Code",
                       lambda: self._emit_action("vscode"))
        menu.addAction(icon("terminal", "#8b93a7"), "Open terminal here",
                       lambda: self._emit_action("terminal"))
        menu.addAction(icon("copy", "#8b93a7"), "Copy path",
                       lambda: self._copy_text(project.path))
        menu.addSeparator()
        menu.addAction(icon("pencil", "#8b93a7"), "Edit…", lambda: self._emit_action("edit"))
        menu.addAction(icon("trash", "#f87171"), "Delete…", lambda: self._emit_action("delete"))
        menu.exec_(event.globalPos())

    def _emit_action(self, action: str) -> None:
        self.action_requested.emit(self._project_id, action)

    def _copy_text(self, text: str) -> None:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            app.clipboard().setText(text)

    # ------------------------------------------------------------------ #

    def refresh(self, project: Optional[Project] = None) -> None:
        """Update all visuals from project data + current status."""
        project = project or self.app.get_project(self._project_id)
        if project is None:
            self.hide()
            return
        self._project = project
        self._status = self.app.status_of(project)
        theme = Theme.instance()
        meta = self.app.detector.meta_for(project.type)

        self._name_label.setText(project.name)
        self._path_label.setText(project.path)
        self._path_label.setToolTip(project.path)

        self._type_icon.setPixmap(
            icon(meta["icon"], meta["color"], 20).pixmap(20, 20)
        )
        self._type_label.setText(meta["label"])
        if project.color:
            self.set_glow_color(project.color)
        else:
            self.set_glow_color(meta["color"])

        self._favorite.setIcon(
            icon("star" if project.favorite else "star_outline",
                 theme.token("warning") if project.favorite else theme.token("text_faint"), 15)
        )

        # Status visuals
        status_color = theme.status_color(self._status.value)
        self._dot.set_color(status_color)
        self._dot.set_pulsing(self._status == ProjectStatus.RUNNING)
        self._restyle_badge(self._status_badge, self._status.label, status_color)
        port_text = f":{project.port}" if project.port else "no port"
        self._restyle_badge(self._port_badge, port_text, theme.token("text_muted"))

        running = self._status.is_active
        primary_state = ("Stop" if running else "Start",
                         "Danger" if running and self._status != ProjectStatus.STOPPING
                         else "Primary")
        if getattr(self, "_primary_state", None) != primary_state:
            self._primary_state = primary_state
            self._primary.setText(primary_state[0])
            self._primary.setObjectName(primary_state[1])
            self._primary.style().unpolish(self._primary)
            self._primary.style().polish(self._primary)

        for name in ("restart", "folder", "browser", "open"):
            button = getattr(self, f"_{name}_button")
            icon_name = {"restart": "restart", "folder": "folder_open",
                         "browser": "globe", "open": "chevron_right"}[name]
            button.setIcon(icon(icon_name, theme.token("text_muted"), 15))
        self._open_button.setIcon(icon("chevron_right", theme.token("text_muted"), 15))

        # Uptime for running processes
        uptime = self.app.processes.uptime_for(project.id)
        self._uptime_label.setText(
            f"up {int(uptime // 60)}m {int(uptime % 60)}s" if uptime > 1 else ""
        )

    @staticmethod
    def _restyle_badge(badge: Badge, text: str, color: str) -> Badge:
        badge.setText(text)
        badge.set_color(color)
        return badge

    # ------------------------------------------------------------------ #

    def animate_in(self, delay_ms: int = 0) -> None:
        """Staggered fade+rise entrance for dashboard refreshes."""
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(260)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.finished.connect(self._install_shadow)
        if delay_ms > 0:
            def _start() -> None:
                try:
                    animation.start()
                except RuntimeError:
                    pass  # card was deleted before the stagger fired

            QTimer.singleShot(delay_ms, _start)
        else:
            animation.start()


class ListRow(QFrame):
    """Compact single-line representation used by the list view mode."""

    action_requested = pyqtSignal(str, str)
    opened = pyqtSignal(str)

    def __init__(self, app: RunHubApplication, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._project_id = project.id
        self.setObjectName("Card")
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)
        self._type_icon = QLabel()
        self._type_icon.setFixedSize(20, 20)
        row.addWidget(self._type_icon)
        self._name = QLabel()
        self._name.setStyleSheet("font-weight: 600;")
        row.addWidget(self._name, 1)
        self._path = QLabel()
        self._path.setObjectName("Faint")
        row.addWidget(self._path, 2)
        self._badge = Badge("Stopped", "#8b93a7")
        row.addWidget(self._badge)
        for action in ("start", "restart", "folder", "browser"):
            button = QToolButton()
            button.setFixedSize(28, 28)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(action.capitalize())
            button.clicked.connect(lambda _, a=action: self.action_requested.emit(self._project_id, a))
            setattr(self, f"_btn_{action}", button)
            row.addWidget(button)
        row.addStretch(1)
        open_button = QToolButton()
        open_button.setFixedSize(28, 28)
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(lambda: self.opened.emit(self._project_id))
        self._btn_open = open_button
        row.addWidget(open_button)
        self.refresh(project)

    @property
    def project_id(self) -> str:
        return self._project_id

    def refresh(self, project: Optional[Project] = None) -> None:
        project = project or self.app.get_project(self._project_id)
        if project is None:
            self.hide()
            return
        theme = Theme.instance()
        meta = self.app.detector.meta_for(project.type)
        self._type_icon.setPixmap(icon(meta["icon"], meta["color"], 16).pixmap(16, 16))
        self._name.setText(project.name)
        self._path.setText(project.path)
        status = self.app.status_of(project)
        self._badge = self._badge.restyle(status.label, theme.status_color(status.value))
        running = status.is_active
        self._btn_start.setIcon(icon("stop", theme.token("danger"), 14))
        self._btn_start.setToolTip("Stop")


# (Badge.restyle helper lives in app.ui.widgets.badge.Badge.restyle)


class DashboardPage(QWidget):
    """The Projects dashboard."""

    open_project = pyqtSignal(str)               # project_id → detail view
    request_add = pyqtSignal()
    request_scan = pyqtSignal()
    request_edit = pyqtSignal(str)               # project_id → edit dialog

    def __init__(self, app: RunHubApplication, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._cards: Dict[str, ProjectCard] = {}
        self._rows: Dict[str, ListRow] = {}
        self._filter_status = "all"
        self._filter_type = "all"
        self._view_mode = "grid"
        self._search_text = ""
        self._build()
        self.rebuild()

        self.app.projects_changed.connect(self.rebuild)
        self.app.project_updated.connect(self._on_project_updated)
        self.app.project_status_changed.connect(self._on_status_changed)

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 10)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self._title = QLabel("Projects")
        self._title.setObjectName("Title")
        self._count_label = QLabel("")
        self._count_label.setObjectName("Muted")
        title_box.addWidget(self._title)
        title_box.addWidget(self._count_label)
        header.addLayout(title_box)
        header.addStretch(1)

        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("Search")
        self._search_edit.setPlaceholderText("Search projects…  (Ctrl+F)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(240)
        self._search_edit.textChanged.connect(self._apply_filters)
        header.addWidget(self._search_edit)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Name", "Type", "Recently started"])
        self._sort_combo.currentIndexChanged.connect(self._apply_filters)
        header.addWidget(self._sort_combo)

        self._view_button = QToolButton()
        self._view_button.setCheckable(False)
        self._view_button.setToolTip("Toggle grid / list view")
        self._view_button.clicked.connect(self._toggle_view)
        header.addWidget(self._view_button)

        scan_button = QPushButton("Scan folder…")
        scan_button.clicked.connect(self.request_scan.emit)
        header.addWidget(scan_button)

        add_button = QPushButton("  New project")
        add_button.setObjectName("Primary")
        add_button.setIcon(icon("plus", "#ffffff", 14))
        add_button.clicked.connect(self.request_add.emit)
        header.addWidget(add_button)
        layout.addLayout(header)

        # Filter chips
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips = {}
        for value, label in (
            ("all", "All"), ("running", "Running"), ("stopped", "Stopped"),
            ("favorites", "Favorites"),
        ):
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setChecked(value == "all")
            chip.setStyleSheet(
                "QPushButton { padding: 3px 12px; border-radius: 12px; font-size: 11px; }"
            )
            chip.clicked.connect(lambda _, v=value: self._select_chip(v))
            self._chips[value] = chip
            chips.addWidget(chip)

        self._type_combo = QComboBox()
        self._type_combo.addItem("All types", userData="all")
        for kind in self.app.detector.kinds():
            meta = self.app.detector.meta_for(kind)
            self._type_combo.addItem(meta["label"], userData=kind)
        self._type_combo.currentIndexChanged.connect(self._apply_filters)
        chips.addWidget(self._type_combo)
        chips.addStretch(1)
        layout.addLayout(chips)

        # Content scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._grid_layout = FlowLayout(self._content, spacing=14)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

        self._empty = self._build_empty()
        self._empty.hide()
        layout.addWidget(self._empty, 1)

        self._refresh_view_button()

    def _build_empty(self) -> QWidget:
        theme = Theme.instance()
        box = QVBoxLayout()
        box.setAlignment(Qt.AlignCenter)
        logo = QLabel()
        logo.setPixmap(icon("box", theme.token("text_faint"), 56).pixmap(56, 56))
        logo.setAlignment(Qt.AlignCenter)
        box.addWidget(logo)
        title = QLabel("No projects yet")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignCenter)
        box.addWidget(title)
        subtitle = QLabel(
            "Add a local project or scan a folder — RunHub detects React, Node,\n"
            "Python, FastAPI, Django and Laravel stacks automatically."
        )
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignCenter)
        box.addWidget(subtitle)
        buttons = QHBoxLayout()
        buttons.setAlignment(Qt.AlignCenter)
        buttons.setSpacing(10)
        add = QPushButton("  Add project")
        add.setObjectName("Primary")
        add.setIcon(icon("plus", "#ffffff", 14))
        add.clicked.connect(self.request_add.emit)
        scan = QPushButton("Scan a folder…")
        scan.clicked.connect(self.request_scan.emit)
        buttons.addWidget(add)
        buttons.addWidget(scan)
        box.addLayout(buttons)
        widget = QWidget()
        widget.setLayout(box)
        return widget

    # ------------------------------------------------------------------ #

    def _select_chip(self, value: str) -> None:
        self._filter_status = value
        for key, chip in self._chips.items():
            chip.setChecked(key == value)
        self._apply_filters()

    def _toggle_view(self) -> None:
        self._view_mode = "list" if self._view_mode == "grid" else "grid"
        self._refresh_view_button()
        self.rebuild()

    def _refresh_view_button(self) -> None:
        theme = Theme.instance()
        self._view_button.setIcon(
            icon("list" if self._view_mode == "grid" else "grid",
                 theme.token("text_muted"), 16)
        )
        self._view_button.setToolTip(
            "Switch to list view" if self._view_mode == "grid" else "Switch to grid view"
        )

    def focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # ------------------------------------------------------------------ #

    def rebuild(self, animate: bool = True) -> None:
        """Recreate the card set (keeps scroll position)."""
        scrollbar = self._scroll.verticalScrollBar()
        position = scrollbar.value()

        # Clear
        for widget in list(self._cards.values()) + list(self._rows.values()):
            widget.setParent(None)
            widget.deleteLater()
        self._cards.clear()
        self._rows.clear()

        projects = self._filtered_projects()
        for index, project in enumerate(projects):
            card = ProjectCard(self.app, project)
            card.action_requested.connect(self._handle_action)
            card.opened.connect(self.open_project.emit)
            self._cards[project.id] = card
            self._grid_layout.addWidget(card)
            if animate:
                card.animate_in(min(index * 40, 400))

            row = ListRow(self.app, project)
            row.action_requested.connect(self._handle_action)
            row.opened.connect(self.open_project.emit)
            self._rows[project.id] = row
            if self._view_mode == "list":
                self._grid_layout.addWidget(row)
            else:
                row.hide()

        self._apply_view_mode()
        self._count_label.setText(f"{len(projects)} shown")
        self._empty.setVisible(len(projects) == 0)
        self._scroll.setVisible(len(projects) > 0 or self._view_mode == "list")
        QTimer.singleShot(0, lambda: scrollbar.setValue(position))

    def _apply_view_mode(self) -> None:
        for project_id, card in self._cards.items():
            card.setVisible(self._view_mode == "grid")
            row = self._rows.get(project_id)
            if row is not None:
                row.setVisible(self._view_mode == "list")

    def _filtered_projects(self) -> List[Project]:
        projects = self.app.project_list()
        query = self._search_text.strip().lower()
        if query:
            projects = [p for p in projects if p.matches(query)]
        if self._filter_status == "running":
            projects = [p for p in projects if self.app.status_of(p).is_active]
        elif self._filter_status == "stopped":
            projects = [p for p in projects if not self.app.status_of(p).is_active]
        elif self._filter_status == "favorites":
            projects = [p for p in projects if p.favorite]
        kind = self._type_combo.currentData() if self._type_combo.currentIndex() >= 0 else "all"
        if kind and kind != "all":
            projects = [p for p in projects if p.type == kind]

        mode = self._sort_combo.currentText() if self._sort_combo.currentIndex() >= 0 else "Name"
        if mode == "Type":
            projects.sort(key=lambda p: (p.type, p.name.lower()))
        elif mode == "Recently started":
            projects.sort(key=lambda p: p.last_started_at, reverse=True)
        else:
            projects.sort(key=lambda p: (not p.favorite, p.name.lower()))
        return projects

    def _apply_filters(self) -> None:
        self.rebuild(animate=False)

    # ------------------------------------------------------------------ #

    def _on_project_updated(self, project_id: str) -> None:
        card = self._cards.get(project_id)
        if card:
            card.refresh()
        row = self._rows.get(project_id)
        if row:
            row.refresh()

    def _on_status_changed(self, project_id: str, status_value: str) -> None:
        card = self._cards.get(project_id)
        if card:
            card.refresh()
        row = self._rows.get(project_id)
        if row:
            row.refresh()
        if self._filter_status in ("running", "stopped"):
            self.rebuild(animate=False)

    def refresh_visible(self) -> None:
        """Periodic refresh (uptime labels)."""
        for card in self._cards.values():
            if self._view_mode == "grid":
                card.refresh()
        for row in self._rows.values():
            if self._view_mode == "list":
                row.refresh()

    # ------------------------------------------------------------------ #

    def _handle_action(self, project_id: str, action: str) -> None:
        project = self.app.get_project(project_id)
        if project is None:
            return
        status = self.app.status_of(project)
        if action == "start" and not status.is_active:
            self.app.start_project(project)
        elif action == "start" and status.is_active:
            self._stop(project)
        elif action == "stop":
            self._stop(project)
        elif action == "restart":
            self.app.restart_project(project)
        elif action == "folder":
            try:
                self.app.workspace.open_folder(project.path)
            except Exception as exc:
                self.app._toast(str(exc), "error", "Open folder")
        elif action == "browser":
            self.app.open_browser(project)
        elif action == "vscode":
            self._open_vscode(project)
        elif action == "terminal":
            self._open_terminal(project)
        elif action == "edit":
            self.request_edit.emit(project_id)
        elif action == "delete":
            self._delete(project)

    def _stop(self, project: Project) -> None:
        if self.app.settings.confirm_stop and not confirm(
            self, "Stop project", f"Stop '{project.name}'?"
        ):
            return
        self.app.stop_project(project)

    def _open_vscode(self, project: Project) -> None:
        try:
            self.app.workspace.open_in_vscode(project.path)
        except Exception as exc:
            self.app._toast(str(exc), "error", "VS Code")

    def _open_terminal(self, project: Project) -> None:
        try:
            self.app.workspace.open_terminal(project.path)
        except Exception as exc:
            self.app._toast(str(exc), "error", "Terminal")

    def _delete(self, project: Project) -> None:
        if confirm(self, "Delete project",
                   f"Delete '{project.name}'?\nRunning processes will be stopped. "
                   "Project files are not touched.", danger=True):
            self.app.delete_project(project.id)

    def bulk_import(self, results) -> None:
        """Show the import checklist for scan results."""
        if not results:
            self.app._toast("No recognizable projects found.", "warn", "Scan")
            return
        dialog = BulkImportDialog(results, self)
        if dialog.exec_() == BulkImportDialog.Accepted:
            added = 0
            for result in dialog.selected_results():
                try:
                    self.app.add_project({
                        "name": result.name or result.path.name,
                        "path": str(result.path),
                        "type": result.kind,
                        "command": result.command,
                        "port": result.port,
                        "description": result.meta,
                        "env": result.env,
                        "auto_open_browser": True,
                    })
                    added += 1
                except Exception as exc:
                    log.warning("Import failed for %s: %s", result.path, exc)
            self.app._toast(f"Imported {added} project(s).", "success", "Scan")
