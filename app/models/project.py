"""Project data model.

A :class:`Project` describes one local development workspace: where it lives,
which command runs it, on which port it serves and how RunHub presents it.
Projects are persisted to ``projects.json`` via :meth:`to_dict`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from app.utils.helpers import new_id, normalize_env, now_iso, parse_bool

log = logging.getLogger(__name__)


class ProjectStatus(str, Enum):
    """Lifecycle states of a managed project process."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"
    ERROR = "error"

    @property
    def label(self) -> str:
        return {
            ProjectStatus.STOPPED: "Stopped",
            ProjectStatus.STARTING: "Starting…",
            ProjectStatus.RUNNING: "Running",
            ProjectStatus.STOPPING: "Stopping…",
            ProjectStatus.CRASHED: "Crashed",
            ProjectStatus.ERROR: "Error",
        }[self]

    @property
    def is_active(self) -> bool:
        """True while a process exists (start has been requested)."""
        return self in (ProjectStatus.STARTING, ProjectStatus.RUNNING, ProjectStatus.STOPPING)


# Metadata for the project "kinds" contributed by detector plugins.
# kind -> (label, icon name, accent color)
TYPE_META: Dict[str, Dict[str, str]] = {
    "react": {"label": "React", "icon": "atom", "color": "#61dafb"},
    "node": {"label": "Node.js", "icon": "hexagon", "color": "#8cc84b"},
    "python": {"label": "Python", "icon": "code", "color": "#4b8bbe"},
    "fastapi": {"label": "FastAPI", "icon": "zap", "color": "#00a39a"},
    "django": {"label": "Django", "icon": "database", "color": "#44b78b"},
    "laravel": {"label": "Laravel", "icon": "layers", "color": "#f05340"},
    "generic": {"label": "Project", "icon": "box", "color": "#8b93a7"},
}


def type_meta(kind: str) -> Dict[str, str]:
    """Return display metadata for a project kind (never raises)."""
    return TYPE_META.get(kind or "generic", TYPE_META["generic"])


@dataclass
class Project:
    """One managed local development project."""

    name: str
    path: str
    id: str = field(default_factory=new_id)
    type: str = "generic"
    command: str = ""
    port: int = 0
    description: str = ""
    tags: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    groups: List[str] = field(default_factory=list)  # profile ids
    favorite: bool = False
    auto_open_browser: bool = True
    allow_shell: bool = False
    color: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    last_started_at: str = ""
    last_exit_code: Optional[int] = None
    run_count: int = 0

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON storage."""
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "command": self.command,
            "port": int(self.port or 0),
            "description": self.description,
            "tags": list(self.tags),
            "env": dict(self.env),
            "groups": list(self.groups),
            "favorite": bool(self.favorite),
            "auto_open_browser": bool(self.auto_open_browser),
            "allow_shell": bool(self.allow_shell),
            "color": self.color,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_started_at": self.last_started_at,
            "last_exit_code": self.last_exit_code,
            "run_count": int(self.run_count),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """Build a Project from stored JSON, filling safe defaults."""
        if not isinstance(data, dict):
            raise ValueError("Project record must be a JSON object.")
        name = str(data.get("name") or "").strip()
        path = str(data.get("path") or "").strip()
        if not name:
            raise ValueError("Project record is missing 'name'.")
        if not path:
            raise ValueError(f"Project '{name}' is missing 'path'.")
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        project = cls(
            id=str(data.get("id") or new_id()),
            name=name,
            path=path,
            type=str(data.get("type") or "generic") or "generic",
            command=str(data.get("command") or "").strip(),
            port=port if 0 <= port <= 65535 else 0,
            description=str(data.get("description") or ""),
            tags=[str(t) for t in (data.get("tags") or []) if str(t).strip()],
            env=normalize_env(data.get("env") or {}),
            groups=[str(g) for g in (data.get("groups") or [])],
            favorite=parse_bool(data.get("favorite")),
            auto_open_browser=parse_bool(data.get("auto_open_browser"), True),
            allow_shell=parse_bool(data.get("allow_shell")),
            color=str(data.get("color") or ""),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
            last_started_at=str(data.get("last_started_at") or ""),
            last_exit_code=data.get("last_exit_code"),
            run_count=int(data.get("run_count") or 0),
        )
        if project.last_exit_code is not None:
            try:
                project.last_exit_code = int(project.last_exit_code)
            except (TypeError, ValueError):
                project.last_exit_code = None
        return project

    # ------------------------------------------------------------------ #
    # Display helpers
    # ------------------------------------------------------------------ #

    @property
    def meta(self) -> Dict[str, str]:
        """Display metadata for this project's kind."""
        return type_meta(self.type)

    @property
    def type_label(self) -> str:
        return self.meta["label"]

    @property
    def url(self) -> str:
        """Primary URL for this project (empty when no port is set)."""
        return f"http://localhost:{self.port}" if self.port else ""

    def matches(self, query: str) -> bool:
        """Case-insensitive multi-field search used by the dashboard filter."""
        q = query.strip().lower()
        if not q:
            return True
        haystack = " ".join(
            [self.name, self.type_label, self.type, self.path, self.description, self.command]
            + list(self.tags)
        ).lower()
        return all(token in haystack for token in q.split())

    def touch(self) -> None:
        """Refresh the ``updated_at`` stamp."""
        self.updated_at = now_iso()

    def mark_started(self) -> None:
        """Record a successful start request."""
        self.last_started_at = now_iso()
        self.run_count += 1
        self.touch()

    def mark_exit(self, code: int) -> None:
        """Record a process exit code."""
        self.last_exit_code = code
        self.touch()
