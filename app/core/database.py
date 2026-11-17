"""JSON database: thread-safe, atomically persisted collections.

RunHub stores everything as human-readable JSON:

    data/
      projects.json    all registered projects
      profiles.json    workspace profiles (project groups)
      settings.json    user preferences
      logs.json        rolling console history per project

The :class:`Database` wraps each file in a :class:`JsonCollection` that
handles loading, schema versioning, atomic saves (temp file + replace)
and corruption recovery via backups.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from app.core.config_manager import (
    LOGS_FILE,
    PROJECTS_FILE,
    PROFILES_FILE,
    SETTINGS_FILE,
    ConfigManager,
)

log = logging.getLogger(__name__)


class JsonCollection:
    """One JSON document on disk with load/save/change-notification."""

    def __init__(
        self,
        name: str,
        config: ConfigManager,
        root_key: str,
        default: Any,
        validate: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.name = name
        self.path = config.collection_path(name)
        self.root_key = root_key
        self._config = config
        self._validate = validate
        self._lock = threading.RLock()
        self._data: Any = default
        self._dirty = False
        self._listeners: List[Callable[[str], None]] = []
        self.load()

    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """(Re)load the document from disk, applying schema normalization."""
        payload = self._config.read_json(self.path, default=None)
        if payload is None or not isinstance(payload, dict) or self.root_key not in payload:
            if payload is not None:
                log.warning("%s: unexpected schema, resetting.", self.name)
            payload = {"version": 1, self.root_key: copy.deepcopy(self._data)}
        data = payload.get(self.root_key)
        if self._validate is not None:
            try:
                data = self._validate(data)
            except Exception as exc:
                log.error("%s: validation failed (%s) — using previous state.", self.name, exc)
                data = self._data
        self._data = data
        self._dirty = False

    def save(self) -> None:
        """Persist the current state (atomic write)."""
        with self._lock:
            payload = {"version": 1, self.root_key: self._data}
            try:
                self._config.write_json(self.path, payload)
                self._dirty = False
            except Exception:
                log.exception("%s: save failed", self.name)

    def data(self) -> Any:
        """Direct access to the underlying document (single-writer pattern)."""
        return self._data

    def snapshot(self) -> Any:
        """Deep copy of the current document (safe to hand to dialogs)."""
        with self._lock:
            return copy.deepcopy(self._data)

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def add_listener(self, callback: Callable[[str], None]) -> None:
        """Register ``callback(name)`` invoked after every save."""
        self._listeners.append(callback)

    def commit(self) -> None:
        """Save and notify listeners."""
        self.save()
        for callback in list(self._listeners):
            try:
                callback(self.name)
            except Exception:
                log.exception("Collection listener failed")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JsonCollection {self.name} dirty={self._dirty}>"


class Database:
    """Facade over the four RunHub collections."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self.projects = JsonCollection(
            PROJECTS_FILE,
            config,
            root_key="projects",
            default=[],
            validate=self._validate_list,
        )
        self.profiles = JsonCollection(
            PROFILES_FILE,
            config,
            root_key="profiles",
            default=[],
            validate=self._validate_list,
        )
        self.settings = JsonCollection(
            SETTINGS_FILE,
            config,
            root_key="settings",
            default={},
            validate=self._validate_dict,
        )
        self.logs = JsonCollection(
            LOGS_FILE,
            config,
            root_key="logs",
            default={},
            validate=self._validate_dict,
        )
        self.collections = [
            self.projects,
            self.profiles,
            self.settings,
            self.logs,
        ]

    # ------------------------------------------------------------------ #
    # Validation hooks
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_list(data: Any) -> List[dict]:
        if not isinstance(data, list):
            raise ValueError("expected a list")
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _validate_dict(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data

    # ------------------------------------------------------------------ #

    def save_all(self) -> None:
        """Persist every collection (used on shutdown)."""
        for collection in self.collections:
            collection.save()

    def backup_all(self) -> List[str]:
        """Timestamped backups of projects/profiles (best effort)."""
        made = []
        for name in (PROJECTS_FILE, PROFILES_FILE):
            path = self.config.backup_collection(name)
            if path:
                made.append(str(path))
        return made
