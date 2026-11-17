"""Profiles page: workspace groups with bulk start/stop/restart actions."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.models.profile import Profile
from app.models.project import ProjectStatus
from app.ui.dialogs import ProfileDialog, confirm
from app.ui.icons import icon
from app.ui.theme import Theme, rgba
from app.ui.widgets.spotlight_card import SpotlightCard
from app.ui.widgets.stat_widgets import StatTile

log = logging.getLogger(__name__)


class ProfileCard(SpotlightCard):
    """One profile card with member chips and bulk actions."""

    action = pyqtSignal(str, str)   # profile_id, action (start/stop/restart/edit/delete)
    open_project = pyqtSignal(str)

    CARD_WIDTH = 322
    CARD_HEIGHT = 210

    def __init__(self, app: RunHubApplication, profile: Profile, parent=None) -> None:
        super().__init__(parent, radius=14, glow=True)
        self.app = app
        self._profile_id = profile.id
        self._profile = profile
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.set_glow_color(profile.color)
        self._build(profile)
        self.refresh(profile)

    # ------------------------------------------------------------------ #

    @property
    def profile_id(self) -> str:
        return self._profile_id

    def _build(self, profile: Profile) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(22, 22)
        top.addWidget(self._icon_label)
        self._name_label = QLabel()
        self._name_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        top.addWidget(self._name_label, 1)
        self._count_badge = QLabel("0")
        self._count_badge.setStyleSheet(
            f"color: {profile.color}; background: {rgba(profile.color, 0.14)};"
            "border-radius: 9px; padding: 2px 10px; font-size: 10px; font-weight: 700;"
        )
        top.addWidget(self._count_badge)
        layout.addLayout(top)

        self._description_label = QLabel()
        self._description_label.setObjectName("Muted")
        self._description_label.setWordWrap(True)
        layout.addWidget(self._description_label)

        # Member chips (flow via wrap layout)
        self._members_label = QLabel()
        self._members_label.setObjectName("Faint")
        self._members_label.setWordWrap(True)
        layout.addWidget(self._members_label, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._start_button = QPushButton("Start all")
        self._start_button.setObjectName("Primary")
        self._start_button.setFixedHeight(30)
        self._start_button.setCursor(Qt.PointingHandCursor)
        self._start_button.clicked.connect(lambda: self.action.emit(self._profile_id, "start"))
        actions.addWidget(self._start_button)
        self._stop_button = QPushButton("Stop all")
        self._stop_button.setFixedHeight(30)
        self._stop_button.setCursor(Qt.PointingHandCursor)
        self._stop_button.clicked.connect(lambda: self.action.emit(self._profile_id, "stop"))
        actions.addWidget(self._stop_button)
        actions.addStretch(1)
        for action_name, icon_name, tooltip in (
            ("restart", "restart", "Restart all"),
            ("edit", "pencil", "Edit profile"),
            ("delete", "trash", "Delete profile"),
        ):
            button = QToolButton()
            button.setFixedSize(30, 30)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _, a=action_name: self.action.emit(self._profile_id, a))
            setattr(self, f"_{action_name}_button", button)
            actions.addWidget(button)
        layout.addLayout(actions)

    def refresh(self, profile: Optional[Profile] = None) -> None:
        profile = profile or self.app.get_profile(self._profile_id)
        if profile is None:
            self.hide()
            return
        self._profile = profile
        theme = Theme.instance()
        self.set_glow_color(profile.color)
        self._icon_label.setPixmap(icon("layers", profile.color, 18).pixmap(18, 18))
        self._name_label.setText(profile.name)
        self._count_badge.setStyleSheet(
            f"color: {profile.color}; background: {rgba(profile.color, 0.14)};"
            "border-radius: 9px; padding: 2px 10px; font-size: 10px; font-weight: 700;"
        )
        self._count_badge.setText(str(len(profile.project_ids)))
        self._description_label.setText(profile.description or "—")
        names = []
        for project_id in profile.project_ids:
            project = self.app.get_project(project_id)
            if project:
                status = self.app.status_of(project)
                mark = "●" if status.is_active else "○"
                names.append(f"{mark} {project.name}")
        self._members_label.setText("   ".join(names) if names else "No projects in this profile yet.")

        for button, icon_name in (
            (self._restart_button, "restart"),
            (self._edit_button, "pencil"),
            (self._delete_button, "trash"),
        ):
            button.setIcon(icon(icon_name, theme.token("text_muted"), 14))


class ProfilesPage(QWidget):
    """Grid of profile cards + summary tiles."""

    open_project = pyqtSignal(str)

    def __init__(self, app: RunHubApplication, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._cards: Dict[str, ProfileCard] = {}
        self._build()
        self.rebuild()
        self.app.profiles_changed.connect(self.rebuild)
        self.app.project_status_changed.connect(self._on_status_changed)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 10)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Profiles")
        title.setObjectName("Title")
        subtitle = QLabel("Group projects and run them together — one click starts the whole stack.")
        subtitle.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        new_button = QPushButton("  New profile")
        new_button.setObjectName("Primary")
        new_button.setIcon(icon("plus", "#ffffff", 14))
        new_button.clicked.connect(self._new_profile)
        header.addWidget(new_button)
        layout.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self._tile_profiles = StatTile("layers", "Profiles")
        self._tile_projects = StatTile("box", "Projects linked")
        self._tile_running = StatTile("pulse", "Running now")
        for tile in (self._tile_profiles, self._tile_projects, self._tile_running):
            tile.setFixedHeight(96)
            stats.addWidget(tile)
        stats.addStretch(1)
        layout.addLayout(stats)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._cards_layout = QHBoxLayout(self._content)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(14)
        self._cards_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

        self._empty = QLabel("No profiles yet — create one to group your stack.")
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty)
        self._empty.setVisible(False)

    def rebuild(self) -> None:
        for card in list(self._cards.values()):
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        profiles = self.app.profile_list()
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for profile in profiles:
            card = ProfileCard(self.app, profile)
            card.action.connect(self._handle_action)
            self._cards[profile.id] = card
            self._cards_layout.addWidget(card)
        self._cards_layout.addStretch(1)
        self._empty.setVisible(not profiles)

        self._tile_profiles.set_value(str(len(profiles)))
        linked = sum(len(p.project_ids) for p in profiles)
        self._tile_projects.set_value(str(linked))
        self._tile_running.set_value(str(self.app.running_count()))

    def _on_status_changed(self, *_args) -> None:
        self._tile_running.set_value(str(self.app.running_count()))
        for card in self._cards.values():
            card.refresh()

    # ------------------------------------------------------------------ #

    def _handle_action(self, profile_id: str, action: str) -> None:
        profile = self.app.get_profile(profile_id)
        if profile is None:
            return
        if action == "start":
            self.app.profile_start(profile)
        elif action == "stop":
            stopped = self.app.profile_stop(profile)
            self.app._toast(f"Stopped {stopped} project(s).", "info", profile.name)
        elif action == "restart":
            count = self.app.profile_restart(profile)
            self.app._toast(f"Restarted {count} project(s).", "info", profile.name)
        elif action == "edit":
            self._edit_profile(profile)
        elif action == "delete":
            if confirm(self, "Delete profile", f"Delete profile '{profile.name}'?", danger=True):
                self.app.delete_profile(profile_id)

    def _new_profile(self) -> None:
        dialog = ProfileDialog(self.app, parent=self)
        if dialog.exec_() == ProfileDialog.Accepted:
            from app.models.profile import Profile as ProfileModel

            data = dialog.profile_data()
            profile = ProfileModel(
                name=data["name"], description=data["description"],
                color=data["color"], project_ids=data["project_ids"],
            )
            self.app.save_profile(profile)

    def _edit_profile(self, profile: Profile) -> None:
        dialog = ProfileDialog(self.app, profile, parent=self)
        if dialog.exec_() == ProfileDialog.Accepted:
            data = dialog.profile_data()
            profile.name = data["name"]
            profile.description = data["description"]
            profile.color = data["color"]
            profile.project_ids = data["project_ids"]
            self.app.save_profile(profile)
