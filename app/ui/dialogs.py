"""Modal dialogs: project editor with live detection, profile editor,
bulk import from folder scan and a themed confirmation box.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QFileInfo, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.models.profile import PROFILE_COLORS, Profile
from app.models.project import Project, ProjectStatus
from app.services.project_detector import DetectionResult
from app.ui.theme import Theme
from app.utils.filesystem import resolve_path
from app.utils.helpers import env_to_lines, lines_to_env, normalize_env

log = logging.getLogger(__name__)


class ColorSwatchRow(QWidget):
    """Row of round color swatches used to pick an accent for a card."""

    color_selected = pyqtSignal(str)

    def __init__(self, colors: List[str], current: str = "", parent=None) -> None:
        super().__init__(parent)
        self._selected = current
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._buttons: List[Tuple[QPushButton, str]] = []
        for color in colors:
            button = QPushButton()
            button.setFixedSize(24, 24)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(color)
            button.clicked.connect(lambda _, c=color: self.select(c))
            row.addWidget(button)
            self._buttons.append((button, color))
        row.addStretch(1)
        Theme.instance().changed.connect(self._repaint)
        self._repaint()

    def select(self, color: str) -> None:
        self._selected = color
        self._repaint()
        self.color_selected.emit(color)

    def selected(self) -> str:
        return self._selected

    def _repaint(self) -> None:
        theme = Theme.instance()
        for button, color in self._buttons:
            border = theme.token("accent") if color == self._selected else theme.token("border")
            width = 2 if color == self._selected else 1
            button.setStyleSheet(
                f"QPushButton {{ background: {color}; border-radius: 12px;"
                f" border: {width}px solid {border}; min-width: 24px; max-width: 24px;"
                f" min-height: 24px; max-height: 24px; padding: 0; }}"
            )


# ---------------------------------------------------------------------- #
# Project dialog
# ---------------------------------------------------------------------- #

class AddOrEditProjectDialog(QDialog):
    """Create or edit a project, with automatic detection preview."""

    def __init__(self, app: RunHubApplication, project: Optional[Project] = None,
                 initial_path: str = "", parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._project = project
        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.setInterval(350)
        self._detect_timer.timeout.connect(self._run_detection)

        self.setWindowTitle("Edit project" if project else "Add project")
        self.setMinimumWidth(560)
        # In edit mode, auto-detection must not rewrite fields while the path
        # is untouched (opening the dialog sets the path text).
        self._original_path = project.path if project else ""
        self._build_ui()
        if project:
            self._fill(project)
        elif initial_path:
            self._path_edit.setText(initial_path)
            self._on_path_changed()

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        theme = Theme.instance()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Edit project" if self._project else "Add project")
        title.setObjectName("Heading")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My React App")
        form.addRow("Name", self._name_edit)

        # Path + browse
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("C:/Projects/my-app")
        self._path_edit.textChanged.connect(self._on_path_changed)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Folder", path_row)

        # Detection preview
        self._detect_label = QLabel("Detection: —")
        self._detect_label.setObjectName("Muted")
        self._detect_label.setWordWrap(True)
        form.addRow("", self._detect_label)

        # Type
        self._type_combo = QComboBox()
        self._refresh_types()
        self._type_combo.currentTextChanged.connect(self._suggest_command)
        form.addRow("Type", self._type_combo)

        # Command
        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("npm run dev")
        form.addRow("Run command", self._command_edit)

        # Port
        self._port_spin = QSpinBox()
        self._port_spin.setRange(0, 65535)
        self._port_spin.setSpecialValueText("auto / none")
        self._port_spin.setSingleStep(1)
        form.addRow("Port", self._port_spin)

        # Description
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("What is this project?")
        form.addRow("Description", self._description_edit)

        # Tags
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("frontend, portfolio, client")
        form.addRow("Tags", self._tags_edit)

        layout.addLayout(form)

        # Environment table
        env_header = QHBoxLayout()
        env_title = QLabel("Environment variables")
        env_title.setObjectName("Heading")
        env_header.addWidget(env_title)
        env_header.addStretch(1)
        add_env = QPushButton("Add row")
        add_env.setObjectName("Ghost")
        add_env.clicked.connect(self._add_env_row)
        remove_env = QPushButton("Remove row")
        remove_env.setObjectName("Ghost")
        remove_env.clicked.connect(self._remove_env_row)
        env_header.addWidget(add_env)
        env_header.addWidget(remove_env)
        layout.addLayout(env_header)

        self._env_table = QTableWidget(0, 2)
        self._env_table.setHorizontalHeaderLabels(["Name", "Value"])
        self._env_table.horizontalHeader().setStretchLastSection(True)
        self._env_table.setColumnWidth(0, 200)
        self._env_table.setFixedHeight(120)
        layout.addWidget(self._env_table)

        # Options
        options = QHBoxLayout()
        options.setSpacing(16)
        self._auto_open_check = QCheckBox("Auto-open browser when server is up")
        self._auto_open_check.setChecked(True)
        self._favorite_check = QCheckBox("Favorite")
        self._shell_check = QCheckBox("Allow shell operators (|, &&, >)")
        self._shell_check.setToolTip("Runs the command through a shell — only enable for trusted commands.")
        options.addWidget(self._auto_open_check)
        options.addWidget(self._favorite_check)
        options.addWidget(self._shell_check)
        options.addStretch(1)
        layout.addLayout(options)

        # Color + profiles
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Card color"))
        self._color_row = ColorSwatchRow(
            ["", "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b", "#10b981", "#0ea5e9"]
        )
        color_row.addWidget(self._color_row)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        profiles_row = QHBoxLayout()
        profiles_row.addWidget(QLabel("Profiles"))
        self._profiles_list = QListWidget()
        self._profiles_list.setFixedHeight(90)
        for profile in self.app.profile_list():
            item = QListWidgetItem(profile.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, profile.id)
            self._profiles_list.addItem(item)
        profiles_row.addWidget(self._profiles_list, 1)
        layout.addLayout(profiles_row)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #

    def _refresh_types(self) -> None:
        self._type_combo.clear()
        detector = self.app.detector
        for kind in detector.kinds():
            meta = detector.meta_for(kind)
            self._type_combo.addItem(f"{meta['label']}", userData=kind)

    def _fill(self, project: Project) -> None:
        self._name_edit.setText(project.name)
        self._path_edit.setText(project.path)
        index = self._type_combo.findData(project.type)
        if index >= 0:
            self._type_combo.setCurrentIndex(index)
        self._command_edit.setText(project.command)
        self._port_spin.setValue(project.port)
        self._description_edit.setText(project.description)
        self._tags_edit.setText(", ".join(project.tags))
        for key, value in sorted(project.env.items()):
            self._add_env_row(key, value)
        self._auto_open_check.setChecked(project.auto_open_browser)
        self._favorite_check.setChecked(project.favorite)
        self._shell_check.setChecked(project.allow_shell)
        if project.color:
            self._color_row.select(project.color)
        for row in range(self._profiles_list.count()):
            item = self._profiles_list.item(row)
            if item.data(Qt.UserRole) in project.groups:
                item.setCheckState(Qt.Checked)

    # ------------------------------------------------------------------ #

    def _browse(self) -> None:
        start = self._path_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose project folder", start)
        if chosen:
            self._path_edit.setText(chosen)

    def _on_path_changed(self) -> None:
        self._detect_timer.start()

    def _run_detection(self) -> None:
        text = self._path_edit.text().strip()
        if not text:
            self._detect_label.setText("Detection: —")
            return
        if self._project is not None and text == self._original_path:
            # Editing with an unchanged folder: keep the stored config.
            self._detect_label.setText("Detection: (unchanged folder — keeping saved settings)")
            self._last_detection = None
            return
        try:
            path = resolve_path(text, must_exist=True)
        except Exception as exc:
            self._detect_label.setText(f"Detection: folder not usable ({exc})")
            return
        result = self.app.detector.detect(path)
        self._last_detection: Optional[DetectionResult] = result
        if result.matched:
            meta = self.app.detector.meta_for(result.kind)
            port_part = f" • port {result.port}" if result.port else ""
            command_part = f" • {result.command}" if result.command else ""
            self._detect_label.setText(
                f"Detection: {meta['label']} ({result.plugin_id}, {result.confidence:.0%})"
                f"{command_part}{port_part}"
                + (f" — {result.meta}" if result.meta else "")
            )
            index = self._type_combo.findData(result.kind)
            if index >= 0:
                self._type_combo.setCurrentIndex(index)
            if result.port:
                self._port_spin.setValue(result.port)
            if result.command:
                self._command_edit.setText(result.command)
            if not self._name_edit.text().strip():
                self._name_edit.setText(result.name or path.name)
        else:
            self._detect_label.setText("Detection: no known stack — choose a type manually.")

    def _suggest_command(self) -> None:
        """Prefill the command box with the kind's canonical dev command."""
        if self._project is not None and self._command_edit.text().strip():
            return  # editing: keep the user's command
        kind = self._type_combo.currentData()
        if not kind:
            return
        suggestions = {
            "react": "npm run dev", "node": "npm run dev",
            "python": "python main.py", "fastapi": "uvicorn main:app --reload",
            "django": "python manage.py runserver", "laravel": "php artisan serve",
        }
        if kind in suggestions and not self._command_edit.text().strip():
            self._command_edit.setText(suggestions[kind])
        port = self.app.detector.default_port_for(kind)
        if port and self._port_spin.value() == 0:
            self._port_spin.setValue(port)

    def _add_env_row(self, key: str = "", value: str = "") -> None:
        row = self._env_table.rowCount()
        self._env_table.insertRow(row)
        self._env_table.setItem(row, 0, QTableWidgetItem(key))
        self._env_table.setItem(row, 1, QTableWidgetItem(value))

    def _remove_env_row(self) -> None:
        row = self._env_table.currentRow()
        if row >= 0:
            self._env_table.removeRow(row)

    # ------------------------------------------------------------------ #

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        path_text = self._path_edit.text().strip()
        if not name:
            self._warn("Name is required.")
            return
        if not path_text:
            self._warn("Project folder is required.")
            return
        try:
            path = resolve_path(path_text, must_exist=True)
            if not path.is_dir():
                self._warn("The path must be a folder.")
                return
            path = str(path)
        except Exception as exc:
            self._warn(str(exc))
            return

        env, errors = {}, []
        for row in range(self._env_table.rowCount()):
            key_item = self._env_table.item(row, 0)
            value_item = self._env_table.item(row, 1)
            key = (key_item.text() if key_item else "").strip()
            value = (value_item.text() if value_item else "")
            normalized = normalize_env({key: value})
            if key and not normalized:
                errors.append(key)
            elif normalized:
                env.update(normalized)
        if errors:
            self._warn(f"Invalid environment variable names: {', '.join(errors)}")
            return

        command = self._command_edit.text().strip()
        data = {
            "id": self._project.id if self._project else None,
            "name": name,
            "path": path,
            "type": self._type_combo.currentData() or "generic",
            "command": command,
            "port": int(self._port_spin.value()),
            "description": self._description_edit.text().strip(),
            "tags": [t.strip() for t in self._tags_edit.text().split(",") if t.strip()],
            "env": env,
            "groups": [],
            "favorite": self._favorite_check.isChecked(),
            "auto_open_browser": self._auto_open_check.isChecked(),
            "allow_shell": self._shell_check.isChecked(),
            "color": self._color_row.selected(),
        }
        groups = []
        for row in range(self._profiles_list.count()):
            item = self._profiles_list.item(row)
            if item.checkState() == Qt.Checked:
                groups.append(item.data(Qt.UserRole))
        data["groups"] = groups

        if not command:
            answer = QMessageBox.question(
                self, "No run command",
                "This project has no run command — you won't be able to start it "
                "until one is set.\n\nSave anyway?",
            )
            if answer != QMessageBox.Yes:
                return
        self._data = data
        self.accept()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Invalid input", message)

    # ------------------------------------------------------------------ #

    def project_data(self) -> Dict:
        """Validated project payload (call after accept())."""
        return getattr(self, "_data", {})


# ---------------------------------------------------------------------- #
# Profile dialog
# ---------------------------------------------------------------------- #

class ProfileDialog(QDialog):
    """Create or edit a profile (project group)."""

    def __init__(self, app: RunHubApplication, profile: Optional[Profile] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._profile = profile
        self.setWindowTitle("Edit profile" if profile else "New profile")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel("Edit profile" if profile else "New profile")
        title.setObjectName("Heading")
        layout.addWidget(title)

        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Backend")
        form.addRow("Name", self._name_edit)
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("API + database mock + worker")
        form.addRow("Description", self._description_edit)
        layout.addLayout(form)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color"))
        self._color_row = ColorSwatchRow(PROFILE_COLORS)
        color_row.addWidget(self._color_row)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        layout.addWidget(QLabel("Projects in this profile"))
        self._projects_list = QListWidget()
        self._projects_list.setFixedHeight(200)
        for project in app.project_list():
            item = QListWidgetItem(f"{project.name}  ({project.type_label})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(Qt.UserRole, project.id)
            member = profile and project.id in profile.project_ids
            item.setCheckState(Qt.Checked if member else Qt.Unchecked)
            self._projects_list.addItem(item)
        layout.addWidget(self._projects_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if profile:
            self._name_edit.setText(profile.name)
            self._description_edit.setText(profile.description)
            self._color_row.select(profile.color)

    def _accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid input", "Profile name is required.")
            return
        selected = []
        for row in range(self._projects_list.count()):
            item = self._projects_list.item(row)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        self._data = {
            "id": self._profile.id if self._profile else None,
            "name": name,
            "description": self._description_edit.text().strip(),
            "color": self._color_row.selected() or "#6366f1",
            "project_ids": selected,
        }
        self.accept()

    def profile_data(self) -> Dict:
        return getattr(self, "_data", {})


# ---------------------------------------------------------------------- #
# Bulk import from folder scan
# ---------------------------------------------------------------------- #

class BulkImportDialog(QDialog):
    """Checklist of detected projects found by scanning a folder."""

    def __init__(self, results: List[DetectionResult], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Detected projects")
        self.setMinimumWidth(620)
        self._results = [r for r in results if r.matched]

        layout = QVBoxLayout(self)
        header = QLabel(f"{len(self._results)} project(s) detected — select what to import:")
        header.setObjectName("Muted")
        layout.addWidget(header)

        self._list = QListWidget()
        for result in self._results:
            meta_label = f" — {result.meta}" if result.meta else ""
            item = QListWidgetItem(
                f"{result.path.name}   [{result.kind}]   {result.command}{meta_label}"
            )
            item.setToolTip(str(result.path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, result)
            self._list.addItem(item)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_results(self) -> List[DetectionResult]:
        selected = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected


# ---------------------------------------------------------------------- #
# Confirmation
# ---------------------------------------------------------------------- #

def confirm(parent, title: str, message: str, danger: bool = False) -> bool:
    """Themed yes/no confirmation. Returns True when the user confirms."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    if danger:
        box.setIcon(QMessageBox.Warning)
    answer = box.exec_()
    return answer == QMessageBox.Yes
