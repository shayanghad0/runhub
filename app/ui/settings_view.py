"""Settings page: appearance, behavior, integrations, storage, plugins, about."""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.models.settings import ACCENTS
from app.services.system_monitor import PSUTIL_AVAILABLE
from app.ui.icons import icon
from app.ui.theme import Theme
from app.ui.widgets.spotlight_card import SpotlightCard
from app.ui.widgets.theme_toggle import ThemeToggle
from app.utils.filesystem import human_size

log = logging.getLogger(__name__)

SHORTCUTS = [
    ("Ctrl + P", "Open the command palette"),
    ("Ctrl + N", "Add a new project"),
    ("Ctrl + O", "Open the current project folder"),
    ("Ctrl + R", "Restart the current project"),
    ("Ctrl + L", "Focus the live log search"),
    ("Ctrl + F", "Focus the dashboard search"),
    ("Ctrl + 1…5", "Jump between pages"),
    ("Ctrl + ,", "Open settings"),
    ("Ctrl + Q", "Quit RunHub"),
    ("Esc", "Back to dashboard / close overlays"),
]


def _section(title: str, subtitle: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("CardSection")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("Heading")
    layout.addWidget(label)
    if subtitle:
        note = QLabel(subtitle)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        layout.addWidget(note)
    return frame


class SettingsPage(QWidget):
    """The Settings page."""

    def __init__(self, app: RunHubApplication, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._plugin_updating = False
        self._key_labels: List[QLabel] = []
        self._build()
        Theme.instance().changed.connect(self._refresh_theme_bits)
        self._refresh_theme_bits()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        layout.addWidget(self._appearance_section())
        layout.addWidget(self._behavior_section())
        layout.addWidget(self._integrations_section())
        layout.addWidget(self._storage_section())
        layout.addWidget(self._plugins_section())
        layout.addWidget(self._shortcuts_section())
        layout.addWidget(self._about_section())
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ #
    # Sections
    # ------------------------------------------------------------------ #

    def _appearance_section(self) -> QFrame:
        section = _section("Appearance", "Theme and accent apply instantly across the app.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Dark mode"))
        self._theme_toggle = ThemeToggle()
        self._theme_toggle.set_dark(Theme.instance().is_dark, animate=False)
        self._theme_toggle.toggled.connect(self._toggle_theme)
        row.addWidget(self._theme_toggle)
        row.addStretch(1)
        section.layout().addLayout(row)

        accent_row = QHBoxLayout()
        accent_row.addWidget(QLabel("Accent color"))
        self._accent_buttons: Dict[str, QPushButton] = {}
        for name, color in ACCENTS.items():
            button = QPushButton(name)
            button.setFixedHeight(26)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: self._set_accent(n))
            self._accent_buttons[name] = button
            accent_row.addWidget(button)
        accent_row.addStretch(1)
        section.layout().addLayout(accent_row)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Base font size"))
        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(8, 14)
        self._font_slider.setValue(self.app.settings.font_size)
        self._font_slider.setFixedWidth(200)
        self._font_slider.valueChanged.connect(self._set_font_size)
        font_row.addWidget(self._font_slider)
        font_row.addStretch(1)
        section.layout().addLayout(font_row)
        self._refresh_accent_buttons()
        return section

    def _behavior_section(self) -> QFrame:
        section = _section("Behavior")
        self._confirm_stop = QCheckBox("Ask for confirmation before stopping a project")
        self._confirm_stop.setChecked(self.app.settings.confirm_stop)
        self._confirm_stop.toggled.connect(self._update_behavior)
        section.layout().addWidget(self._confirm_stop)

        self._confirm_quit = QCheckBox("Ask before quitting while projects are running")
        self._confirm_quit.setChecked(self.app.settings.confirm_quit_running)
        self._confirm_quit.toggled.connect(self._update_behavior)
        section.layout().addWidget(self._confirm_quit)

        self._auto_browser = QCheckBox("Open the browser automatically when a server comes online")
        self._auto_browser.setChecked(self.app.settings.auto_open_browser)
        self._auto_browser.toggled.connect(self._update_behavior)
        section.layout().addWidget(self._auto_browser)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("System monitor interval"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(500, 10000)
        self._interval_spin.setSingleStep(250)
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.setValue(self.app.settings.monitor_interval_ms)
        self._interval_spin.valueChanged.connect(self._update_behavior)
        interval_row.addWidget(self._interval_spin)
        interval_row.addStretch(1)
        section.layout().addLayout(interval_row)
        return section

    def _integrations_section(self) -> QFrame:
        section = _section(
            "Integrations",
            "RunHub auto-detects VS Code and terminals. Override the paths here if needed.",
        )
        status = self.app.workspace.install_status()
        vscode = status.get("vscode")
        vscode_label = QLabel(
            f"VS Code: {'✓ detected — ' + str(vscode) if vscode else '✗ not found'}"
        )
        vscode_label.setObjectName("Muted")
        section.layout().addWidget(vscode_label)

        editor_row = QHBoxLayout()
        self._editor_edit = QLineEdit()
        self._editor_edit.setPlaceholderText("Path to code / Code.exe (empty = auto-detect)")
        self._editor_edit.setText(self.app.settings.editor_path)
        browse = QPushButton("Browse…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse_editor)
        editor_row.addWidget(self._editor_edit, 1)
        editor_row.addWidget(browse)
        section.layout().addLayout(editor_row)

        terminals = status.get("terminals", [])
        terminal_names = ", ".join(label for _, label in terminals) or "none found"
        terminal_label = QLabel(f"Terminals detected: {terminal_names}")
        terminal_label.setObjectName("Muted")
        terminal_label.setWordWrap(True)
        section.layout().addLayout(QHBoxLayout(), 0)  # spacer keep-alive
        section.layout().addWidget(terminal_label)
        return section

    def _storage_section(self) -> QFrame:
        section = _section(
            "Storage",
            "All data lives as plain JSON files — nothing ever leaves this machine.",
        )
        data_label = QLabel(f"Data directory: {self.app.config.data_dir}")
        data_label.setObjectName("Muted")
        data_label.setWordWrap(True)
        data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        section.layout().addWidget(data_label)

        row = QHBoxLayout()
        open_folder = QPushButton(" Open data folder")
        open_folder.setIcon(icon("folder_open", Theme.instance().token("text_muted"), 14))
        open_folder.clicked.connect(self._open_data_dir)
        export_button = QPushButton(" Export workspace…")
        export_button.setIcon(icon("upload", Theme.instance().token("text_muted"), 14))
        export_button.clicked.connect(self._export)
        import_button = QPushButton(" Import workspace…")
        import_button.setIcon(icon("download", Theme.instance().token("text_muted"), 14))
        import_button.clicked.connect(self._import)
        for button in (open_folder, export_button, import_button):
            row.addWidget(button)
        row.addStretch(1)
        section.layout().addLayout(row)
        return section

    def _plugins_section(self) -> QFrame:
        section = _section(
            "Plugins",
            "Detectors from the plugins/ folder. Add your own — see docs/USAGE.md.",
        )
        self._plugin_list = QListWidget()
        self._plugin_list.setFixedHeight(min(240, 30 + 26 * 8))
        self._plugin_list.itemChanged.connect(self._on_plugin_item_changed)
        section.layout().addWidget(self._plugin_list)
        reload_row = QHBoxLayout()
        reload_button = QPushButton(" Reload plugins")
        reload_button.setIcon(icon("restart", Theme.instance().token("text_muted"), 14))
        reload_button.clicked.connect(self._reload_plugins)
        reload_row.addWidget(reload_button)
        reload_row.addStretch(1)
        section.layout().addLayout(reload_row)
        self._refresh_plugin_list()
        return section

    def _shortcuts_section(self) -> QFrame:
        section = _section("Keyboard shortcuts")
        grid = QHBoxLayout()
        column_left = QVBoxLayout()
        column_right = QVBoxLayout()
        for index, (keys, description) in enumerate(SHORTCUTS):
            row = QHBoxLayout()
            key_label = QLabel(keys)
            key_label.setFixedWidth(90)
            self._key_labels.append(key_label)
            row.addWidget(key_label)
            row.addWidget(QLabel(description))
            row.addStretch(1)
            (column_left if index < len(SHORTCUTS) // 2 + 1 else column_right).addLayout(row)
        grid.addLayout(column_left)
        grid.addLayout(column_right)
        section.layout().addLayout(grid)
        return section

    def _refresh_theme_bits(self) -> None:
        """Re-style accent-colored bits after a theme/accent change."""
        theme = Theme.instance()
        accent = theme.token("accent")
        for key_label in self._key_labels:
            key_label.setStyleSheet(
                f"color: {accent}; font-weight: 600; font-size: 11px;"
            )
        if hasattr(self, "_theme_toggle"):
            self._theme_toggle.set_dark(theme.is_dark, animate=False)

    def _about_section(self) -> QFrame:
        section = _section("About")
        row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon("logo", Theme.instance().token("accent"), 44).pixmap(44, 44))
        row.addWidget(logo)
        box = QVBoxLayout()
        name = QLabel("RunHub")
        name.setStyleSheet("font-size: 17px; font-weight: 700;")
        box.addWidget(name)
        from app.core.config_manager import APP_VERSION

        version = QLabel(
            f"Version {APP_VERSION} — open-source developer workspace manager.\n"
            "Local-first: JSON storage, subprocess processes, no cloud. MIT licensed."
        )
        version.setObjectName("Muted")
        version.setWordWrap(True)
        box.addWidget(version)
        row.addLayout(box, 1)
        section.layout().addLayout(row)
        return section

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def _toggle_theme(self, dark: bool) -> None:
        self.app.settings.theme_mode = "dark" if dark else "light"
        Theme.instance().configure(
            self.app.settings.theme_mode,
            self.app.settings.accent_name,
            self.app.settings.font_size,
        )
        self.app.save_settings()

    def _set_accent(self, name: str) -> None:
        self.app.settings.accent_name = name
        Theme.instance().configure(
            self.app.settings.theme_mode, name, self.app.settings.font_size
        )
        self.app.save_settings()
        self._refresh_accent_buttons()

    def _refresh_accent_buttons(self) -> None:
        theme = Theme.instance()
        for name, button in self._accent_buttons.items():
            color = ACCENTS[name]
            selected = name == self.app.settings.accent_name
            button.setStyleSheet(
                f"QPushButton {{ background: {color}; color: #ffffff;"
                f" border: {'2px' if selected else '1px'} solid "
                f"{theme.token('text') if selected else color};"
                " border-radius: 13px; padding: 2px 12px; font-size: 11px; font-weight: 600; }}"
            )

    def _set_font_size(self, value: int) -> None:
        self.app.settings.font_size = int(value)
        Theme.instance().configure(
            self.app.settings.theme_mode,
            self.app.settings.accent_name,
            int(value),
        )
        self.app.save_settings()

    def _update_behavior(self, *_args) -> None:
        self.app.settings.confirm_stop = self._confirm_stop.isChecked()
        self.app.settings.confirm_quit_running = self._confirm_quit.isChecked()
        self.app.settings.auto_open_browser = self._auto_browser.isChecked()
        self.app.settings.monitor_interval_ms = int(self._interval_spin.value())
        self.app.save_settings()
        self.app.monitor.set_interval(self.app.settings.monitor_interval_ms)

    def _browse_editor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the editor executable", "", "Executables (*.exe *.cmd *.sh);;All files (*)"
        )
        if path:
            self._editor_edit.setText(path)
            self.app.settings.editor_path = path
            self.app.apply_settings(self.app.settings)

    def _open_data_dir(self) -> None:
        try:
            self.app.workspace.open_folder(str(self.app.config.data_dir))
        except Exception as exc:
            self.app._toast(str(exc), "error", "Storage")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export workspace", "runhub-workspace.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.app.export_workspace(), handle, indent=2, ensure_ascii=False)
            self.app._toast("Workspace exported.", "success", "Export")
        except OSError as exc:
            self.app._toast(f"Export failed: {exc}", "error", "Export")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import workspace", "", "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            projects, profiles = self.app.import_workspace(payload, replace=False)
            self.app._toast(f"Imported {projects} projects, {profiles} profiles.",
                            "success", "Import")
            self._refresh_plugin_list()
        except Exception as exc:
            self.app._toast(f"Import failed: {exc}", "error", "Import")

    def _refresh_plugin_list(self) -> None:
        self._plugin_updating = True
        try:
            self._plugin_list.clear()
            loader = self.app.loader
            for wrapper in loader.all_known():
                plugin = wrapper.plugin
                item = QListWidgetItem(
                    f"{plugin.name}  v{plugin.version}  —  {plugin.description or 'detector'}"
                )
                item.setIcon(icon("shield" if plugin.builtin else "box",
                                  Theme.instance().token("accent"), 14))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if self.app.settings.plugin_enabled(plugin.id) else Qt.Unchecked
                )
                item.setData(Qt.UserRole, plugin.id)
                self._plugin_list.addItem(item)
            for error in loader.load_errors:
                self._plugin_list.addItem(QListWidgetItem(f"⚠ {error}"))
        finally:
            self._plugin_updating = False

    def _on_plugin_item_changed(self, item: QListWidgetItem) -> None:
        """Enable/disable a detector when its checkbox is toggled."""
        if self._plugin_updating:
            return
        plugin_id = item.data(Qt.UserRole)
        checked = item.checkState() == Qt.Checked
        if not plugin_id or self.app.settings.plugin_enabled(plugin_id) == checked:
            return
        self.app.settings.plugins_enabled[plugin_id] = checked
        # Defer: this handler is invoked from itemChanged, and the refresh
        # below deletes the very item that is mid-signal.
        QTimer.singleShot(0, lambda: self._apply_plugin_toggle(plugin_id, checked))

    def _apply_plugin_toggle(self, plugin_id: str, checked: bool) -> None:
        self.app.apply_settings(self.app.settings)
        self._refresh_plugin_list()
        self.app._toast(
            f"{plugin_id} detector {'enabled' if checked else 'disabled'}.",
            "info", "Plugins",
        )

    def _reload_plugins(self) -> None:
        self.app.loader.reload(is_enabled=self.app.settings.plugin_enabled, app=self.app)
        self.app.detector.refresh_meta()
        self._refresh_plugin_list()
        self.app._toast("Plugins reloaded.", "success", "Plugins")

    def refresh(self) -> None:
        """Called when the page becomes visible."""
        self._refresh_plugin_list()
