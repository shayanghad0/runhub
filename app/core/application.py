"""RunHub application facade.

:class:`RunHubApplication` is the service locator shared by every UI page:

* owns the JSON database and the in-memory project/profile registries,
* wires the process, log, browser, workspace, detector and monitor services,
* provides CRUD + bulk actions used by the views and the command palette,
* bridges low-level service signals into UI-friendly ones (toasts).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core.config_manager import ConfigManager
from app.core.database import Database
from app.models.profile import DEFAULT_PROFILES, Profile
from app.models.project import Project, ProjectStatus
from app.models.settings import AppSettings
from app.services.browser_manager import BrowserManager
from app.services.log_manager import LogManager
from app.services.plugin_loader import PluginLoader
from app.services.process_manager import ProcessManager
from app.services.project_detector import ProjectDetector
from app.services.system_monitor import SystemMonitor
from app.services.workspace_manager import WorkspaceManager
from app.utils.helpers import new_id, now_iso

log = logging.getLogger(__name__)


class ValidationError(Exception):
    """User-facing data validation failure (shown as a dialog/toast)."""


class RunHubApplication(QObject):
    """Central application object passed to every view."""

    projects_changed = pyqtSignal()
    project_updated = pyqtSignal(str)                 # project_id
    profiles_changed = pyqtSignal()
    project_status_changed = pyqtSignal(str, str)     # project_id, status value
    toast_requested = pyqtSignal(str, str, str)       # message, level, title

    START_STAGGER_MS = 700   # delay between sequential profile starts

    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.db = Database(config)

        self.settings = AppSettings.from_dict(self.db.settings.data() or {})

        self.projects: Dict[str, Project] = {}
        self.profiles: Dict[str, Profile] = {}
        self._statuses: Dict[str, ProjectStatus] = {}

        # Services ------------------------------------------------------- #
        self.logs = LogManager(
            self.db,
            buffer_lines=self.settings.log_buffer_lines,
            persist_lines=self.settings.log_persist_lines,
        )
        self.processes = ProcessManager(self.logs)
        self.processes._project_lookup = self.get_project
        self.browser = BrowserManager()
        self.workspace = WorkspaceManager(
            editor_path=self.settings.editor_path, terminal_path=self.settings.terminal_path
        )
        self.loader = PluginLoader(config.plugin_dir)
        self.detector = ProjectDetector(self.loader)
        self.monitor = SystemMonitor(interval_ms=self.settings.monitor_interval_ms)

        self._bulk_running = False

    # ------------------------------------------------------------------ #
    # Bootstrap / shutdown
    # ------------------------------------------------------------------ #

    def bootstrap(self) -> None:
        """Load data, load plugins and connect service signals."""
        self._load_projects()
        self._load_profiles()
        if not self.db.settings.data():
            self.db.settings.data().update(self.settings.to_dict())
            self.db.settings.commit()

        self.loader.load_all(
            is_enabled=self.settings.plugin_enabled, app=self
        )
        self.detector.refresh_meta()

        # Service → application signal bridges --------------------------- #
        self.processes.state_changed.connect(self._on_state_changed)
        self.processes.failed.connect(self._on_failed)
        self.logs.urls_detected.connect(self._on_urls_detected)
        self.browser.port_ready.connect(self._on_port_ready)

        self.logs.start()
        self.monitor.start()

        if not self.settings.first_run_done:
            self._seed_defaults()
            self.settings.first_run_done = True
            self.save_settings()
        log.info("Application ready — %d project(s), %d profile(s).",
                 len(self.projects), len(self.profiles))

    def shutdown(self) -> None:
        """Flush state and terminate every managed process."""
        log.info("Shutting down…")
        self.monitor.stop()
        self.logs.stop()
        self.browser.shutdown()
        self.processes.stop_all(timeout=12.0)
        self.loader.unload_all()
        self.db.save_all()

    # ------------------------------------------------------------------ #
    # Seed data (first run)
    # ------------------------------------------------------------------ #

    def _seed_defaults(self) -> None:
        """Create the five starter profiles on first launch."""
        for seed in DEFAULT_PROFILES:
            profile = Profile(name=seed["name"], description=seed["description"],
                              color=seed["color"])
            self.profiles[profile.id] = profile
        self._persist_profiles()
        log.info("Seeded default profiles.")

    # ------------------------------------------------------------------ #
    # Project registry
    # ------------------------------------------------------------------ #

    def _load_projects(self) -> None:
        self.projects = {}
        for raw in self.db.projects.data():
            try:
                project = Project.from_dict(raw)
            except (ValueError, TypeError) as exc:
                log.warning("Skipping invalid project record: %s", exc)
                continue
            self.projects[project.id] = project
            self._statuses[project.id] = ProjectStatus.STOPPED

    def project_list(self) -> List[Project]:
        """Projects sorted favorites-first, then by name."""
        items = list(self.projects.values())
        items.sort(key=lambda p: (not p.favorite, p.name.lower()))
        return items

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.projects.get(project_id)

    def status_of(self, project: Project) -> ProjectStatus:
        return self._statuses.get(project.id, ProjectStatus.STOPPED)

    def add_project(self, data: dict) -> Project:
        """Create + persist a project from dialog data."""
        project = Project.from_dict(data)
        project.id = data.get("id") or new_id()
        if any(p.path.lower() == project.path.lower() for p in self.projects.values()):
            raise ValidationError(f"A project already exists for '{project.path}'.")
        self.projects[project.id] = project
        self._statuses[project.id] = ProjectStatus.STOPPED
        self._persist_projects()
        self.projects_changed.emit()
        log.info("Added project %s (%s)", project.name, project.type)
        return project

    def update_project(self, project: Project) -> None:
        """Persist changes made to a project object in place."""
        project.touch()
        self.projects[project.id] = project
        self._persist_projects()
        self.project_updated.emit(project.id)
        self.projects_changed.emit()

    def delete_project(self, project_id: str) -> bool:
        """Stop (if running) and remove a project."""
        project = self.projects.get(project_id)
        if project is None:
            return False
        if self.processes.is_running(project_id):
            self.processes.stop(project_id)
        for key, handle in list(self.processes.aux_for_project(project_id).items()):
            self.processes.stop_aux(project_id, key)
        self.projects.pop(project_id, None)
        self._statuses.pop(project_id, None)
        self.logs.forget(project_id)
        for profile in self.profiles.values():
            if project_id in profile.project_ids:
                profile.project_ids.remove(project_id)
                profile.touch()
        self._persist_projects()
        self._persist_profiles()
        self.projects_changed.emit()
        self.profiles_changed.emit()
        log.info("Deleted project %s", project.name)
        return True

    def duplicate_project(self, project_id: str) -> Optional[Project]:
        """Clone a project definition (path kept, rename suffix added)."""
        source = self.get_project(project_id)
        if source is None:
            return None
        data = source.to_dict()
        data.pop("id", None)
        data["name"] = f"{source.name} (copy)"
        try:
            return self.add_project(data)
        except ValidationError:
            return None

    def toggle_favorite(self, project_id: str) -> None:
        project = self.get_project(project_id)
        if project:
            project.favorite = not project.favorite
            self.update_project(project)

    # ------------------------------------------------------------------ #
    # Lifecycle actions
    # ------------------------------------------------------------------ #

    def start_project(self, project: Project) -> bool:
        """Start a project and (optionally) auto-open its browser."""
        if not project.command.strip():
            self._toast(f"Set a run command for '{project.name}' first.", "warn", "No command")
            return False
        ok = self.processes.start(project)
        if ok:
            self._persist_projects()
            if project.port and project.auto_open_browser and self.settings.auto_open_browser:
                self.browser.wait_and_open(project.id, project.port)
        return ok

    def stop_project(self, project: Project) -> bool:
        return self.processes.stop(project.id)

    def restart_project(self, project: Project) -> None:
        if not project.command.strip():
            self._toast(f"Set a run command for '{project.name}' first.", "warn", "No command")
            return
        self.processes.restart(project)

    def open_browser(self, project: Project) -> None:
        if project.port:
            self.browser.open_project(project)
        else:
            self._toast("No port configured for this project.", "warn", "Open browser")

    # ------------------------------------------------------------------ #
    # Profiles
    # ------------------------------------------------------------------ #

    def _load_profiles(self) -> None:
        self.profiles = {}
        for raw in self.db.profiles.data():
            try:
                profile = Profile.from_dict(raw)
            except (ValueError, TypeError) as exc:
                log.warning("Skipping invalid profile record: %s", exc)
                continue
            self.profiles[profile.id] = profile

    def profile_list(self) -> List[Profile]:
        items = list(self.profiles.values())
        items.sort(key=lambda p: p.name.lower())
        return items

    def get_profile(self, profile_id: str) -> Optional[Profile]:
        return self.profiles.get(profile_id)

    def save_profile(self, profile: Profile) -> None:
        self.profiles[profile.id] = profile
        profile.touch()
        self._persist_profiles()
        self.profiles_changed.emit()

    def delete_profile(self, profile_id: str) -> bool:
        if self.profiles.pop(profile_id, None) is None:
            return False
        self._persist_profiles()
        self.profiles_changed.emit()
        return True

    def profile_start(self, profile: Profile) -> int:
        """Start every member project sequentially (staggered)."""
        if self._bulk_running:
            self._toast("A bulk operation is already running.", "warn", "Busy")
            return 0
        members = [self.projects[pid] for pid in profile.project_ids if pid in self.projects]
        if not members:
            self._toast(f"Profile '{profile.name}' has no projects yet.", "warn", profile.name)
            return 0
        self._bulk_running = True
        started = 0
        for index, project in enumerate(members):
            if not self.processes.is_running(project.id) and project.command.strip():
                self.processes.start(project, delay_ms=index * self.START_STAGGER_MS)
                started += 1
        self._bulk_running = False
        self._toast(f"Started {started}/{len(members)} projects.", "info", profile.name)
        return started

    def profile_stop(self, profile: Profile) -> int:
        members = [self.projects[pid] for pid in profile.project_ids if pid in self.projects]
        stopped = 0
        for project in members:
            if self.processes.is_running(project.id):
                self.processes.stop(project.id)
                stopped += 1
        return stopped

    def profile_restart(self, profile: Profile) -> int:
        members = [self.projects[pid] for pid in profile.project_ids if pid in self.projects]
        count = 0
        for index, project in enumerate(members):
            if project.command.strip():
                if self.processes.is_running(project.id):
                    self.processes.restart(project)
                else:
                    self.processes.start(project, delay_ms=index * self.START_STAGGER_MS)
                count += 1
        return count

    # ------------------------------------------------------------------ #
    # Settings / persistence
    # ------------------------------------------------------------------ #

    def save_settings(self) -> None:
        self.db.settings.data().clear()
        self.db.settings.data().update(self.settings.to_dict())
        self.db.settings.commit()

    def apply_settings(self, settings: AppSettings) -> None:
        """Apply a new settings object live (theme handled by the UI)."""
        self.settings = settings
        self.logs.buffer_lines = settings.log_buffer_lines
        self.logs.persist_lines = settings.log_persist_lines
        self.monitor.set_interval(settings.monitor_interval_ms)
        self.workspace = WorkspaceManager(
            editor_path=settings.editor_path, terminal_path=settings.terminal_path
        )
        self.save_settings()
        # Re-evaluate plugin toggles.
        self.loader.reload(is_enabled=settings.plugin_enabled, app=self)
        self.detector.refresh_meta()

    def export_workspace(self) -> dict:
        """Full JSON bundle for backup/migration."""
        return {
            "app": "RunHub",
            "version": 1,
            "exported_at": now_iso(),
            "projects": [p.to_dict() for p in self.projects.values()],
            "profiles": [p.to_dict() for p in self.profiles.values()],
            "settings": self.settings.to_dict(),
        }

    def import_workspace(self, payload: dict, replace: bool = True) -> Tuple[int, int]:
        """Import projects/profiles from an export bundle."""
        if not isinstance(payload, dict) or payload.get("app") != "RunHub":
            raise ValidationError("Not a RunHub export file.")
        projects_in = [p for p in payload.get("projects", []) if isinstance(p, dict)]
        profiles_in = [p for p in payload.get("profiles", []) if isinstance(p, dict)]
        if replace:
            for project in list(self.projects.values()):
                self.delete_project(project.id)
            self.profiles.clear()
        count_p = count_f = 0
        for raw in projects_in:
            try:
                self.add_project(raw)
                count_p += 1
            except ValidationError as exc:
                log.warning("Import skipped project: %s", exc)
        for raw in profiles_in:
            try:
                profile = Profile.from_dict(raw)
                self.save_profile(profile)
                count_f += 1
            except (ValueError, TypeError) as exc:
                log.warning("Import skipped profile: %s", exc)
        self.projects_changed.emit()
        self.profiles_changed.emit()
        return count_p, count_f

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _persist_projects(self) -> None:
        self.db.projects.data().clear()
        self.db.projects.data().extend(p.to_dict() for p in self.projects.values())
        self.db.projects.commit()

    def _persist_profiles(self) -> None:
        self.db.profiles.data().clear()
        self.db.profiles.data().extend(p.to_dict() for p in self.profiles.values())
        self.db.profiles.commit()

    # ------------------------------------------------------------------ #
    # Signal bridges
    # ------------------------------------------------------------------ #

    def _on_state_changed(self, project_id: str, status_value: str) -> None:
        try:
            status = ProjectStatus(status_value)
        except ValueError:
            return
        self._statuses[project_id] = status
        self.project_status_changed.emit(project_id, status_value)

    def _on_failed(self, project_id: str, message: str) -> None:
        project = self.get_project(project_id)
        title = project.name if project else "Project"
        self._toast(message, "error", title)

    def _on_urls_detected(self, project_id: str, urls: List[str]) -> None:
        """Auto-learn the port when a dev server announces one."""
        project = self.get_project(project_id)
        if project is None or project.port:
            return
        import re

        for url in urls:
            match = re.search(r":(\d{2,5})", url)
            if not match:
                continue
            port = int(match.group(1))
            if 0 < port < 65536 and port not in (80, 443):
                project.port = port
                self.update_project(project)
                self._toast(f"Detected port {port} for '{project.name}'.", "info", "Port detected")
                if project.auto_open_browser and self.settings.auto_open_browser:
                    self.browser.wait_and_open(project_id, port)
                break

    def _on_port_ready(self, project_id: str, port: int, success: bool) -> None:
        if not success:
            return
        project = self.get_project(project_id)
        if project:
            self.logs.system(project_id, f"Server answering on localhost:{port}")

    def _toast(self, message: str, level: str = "info", title: str = "") -> None:
        self.toast_requested.emit(message, level, title)

    # ------------------------------------------------------------------ #
    # Stats used by the status bar
    # ------------------------------------------------------------------ #

    def running_count(self) -> int:
        return sum(1 for pid in self.projects if self.processes.is_running(pid))
